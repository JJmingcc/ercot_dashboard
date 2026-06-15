"""Meteologica 'API markets' client.

Confirmed against the live OpenAPI spec at GET /api/v1/oas (OpenAPI 3.1), 2026-06-09.

Auth: log in once, then pass the returned token as a **query parameter** on every
call (this API does NOT use an Authorization header):

    POST {base_url}/api/v1/login   {"user": ..., "password": ...}
      -> 200 {"token": "<JWT>", "expiration_date": "2026-06-09T23:25:23Z"}
      -> 200 {"message": "<error>"}                       (auth failure)

    GET  {base_url}/api/v1/contents?token=<JWT>           (and all other endpoints)
      -> 400 {"message": "Error. Invalid token"}          (expired/invalid token)

Endpoints (all GET, all require ?token=):
    /api/v1/contents                                   catalog of available contents
    /api/v1/contents/{id}/data                          latest data for a content
    /api/v1/contents/{id}/historical_data/{year}/{month}
    /api/v1/contents/{id}/updates                       updates in a date range
    /api/v1/latest                                      recently-updated contents
    /api/v1/keepalive                                   renew the token
"""
from __future__ import annotations

import io
import json
import logging
import pathlib
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from .config import PROJECT_ROOT, Settings, get_settings

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
LOGIN_PATH = f"{API_PREFIX}/login"
# Refresh the token a little before it actually expires to avoid edge races.
_EXPIRY_SKEW_SECONDS = 60
# Token is cached here so separate processes/clients reuse it instead of
# re-logging in every time (the API rate-limits the login endpoint).
_DEFAULT_TOKEN_CACHE = PROJECT_ROOT / "data" / ".mtoken.json"


class MeteologicaError(RuntimeError):
    """Base error for anything the Meteologica API reports."""


class AuthError(MeteologicaError):
    """Login failed (bad credentials, locked account, or unexpected response)."""


def _parse_expiration(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp like '2026-06-09T23:25:23Z' as tz-aware UTC."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning(
            "Could not parse token expiration %r; will rely on an error to detect expiry.",
            value,
        )
        return None


# Process-level cache of the contents catalog (per base_url). Every consumer (net-load registry,
# zonal demand, …) shares one fetch for a few minutes so a cold render doesn't trip the throttle.
_CONTENTS_CACHE: dict[str, tuple[float, list]] = {}
_CONTENTS_TTL = 300.0  # seconds


class MeteologicaClient:
    def __init__(
        self, settings: Optional[Settings] = None,
        token_cache: Optional[pathlib.Path] = _DEFAULT_TOKEN_CACHE,
    ) -> None:
        self.settings = settings or get_settings()
        self.session = requests.Session()
        self._token: Optional[str] = None
        self._token_expiration: Optional[datetime] = None
        self._token_cache = pathlib.Path(token_cache) if token_cache else None
        self._load_cached_token()

    def _load_cached_token(self) -> None:
        """Reuse a previously stored token (across processes) if still valid."""
        if not self._token_cache or not self._token_cache.exists():
            return
        try:
            data = json.loads(self._token_cache.read_text())
        except (OSError, ValueError):
            return
        self._token = data.get("token")
        self._token_expiration = _parse_expiration(data.get("expiration_date", ""))
        if not self.token_valid:  # expired cache -> discard
            self._token = None
            self._token_expiration = None

    def _save_cached_token(self) -> None:
        if not self._token_cache:
            return
        try:
            self._token_cache.parent.mkdir(parents=True, exist_ok=True)
            exp = self._token_expiration.isoformat() if self._token_expiration else ""
            self._token_cache.write_text(json.dumps({"token": self._token, "expiration_date": exp}))
        except OSError:
            logger.warning("Could not write token cache to %s", self._token_cache)

    def _url(self, path: str) -> str:
        """Join base_url and a path with exactly one separating slash."""
        return f"{self.settings.base_url}/{path.lstrip('/')}"

    # --- auth -------------------------------------------------------------
    @property
    def token_valid(self) -> bool:
        """True if we hold a token that is not (about to be) expired."""
        if not self._token:
            return False
        if self._token_expiration is None:
            return True  # no expiry info; rely on an "Invalid token" error instead
        now = datetime.now(timezone.utc)
        return (self._token_expiration - now).total_seconds() > _EXPIRY_SKEW_SECONDS

    @property
    def token_prefix(self) -> str:
        """A short, non-sensitive fragment for logging/display (never the full token)."""
        return f"{self._token[:8]}…" if self._token else "<none>"

    def _store_token(self, data: dict[str, Any]) -> None:
        token = data.get("token")
        if not token:
            raise AuthError(f"Auth response had no token: {data!r}")
        self._token = token
        self._token_expiration = _parse_expiration(data.get("expiration_date", ""))
        self._save_cached_token()

    def login(self) -> None:
        """Authenticate against /api/v1/login and store the access token.

        Raises AuthError on a {"message": ...} error body or a missing token.
        """
        url = self._url(LOGIN_PATH)
        try:
            resp = self.session.post(
                url,
                json={"user": self.settings.username, "password": self.settings.password},
                timeout=30,
                allow_redirects=False,  # a redirect here means a misconfigured base_url
            )
        except requests.RequestException as exc:
            raise AuthError(f"Could not reach login endpoint {url}: {exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise AuthError(
                f"Login returned non-JSON response (HTTP {resp.status_code}): "
                f"{resp.text[:200]!r}"
            ) from exc

        # The API signals failure with a "message" field rather than an HTTP error.
        if "message" in data:
            raise AuthError(f"Login rejected: {data['message']}")
        self._store_token(data)

    def keepalive(self) -> None:
        """Renew the current token without re-sending credentials.

        Falls back to a full login if there is no token yet.
        """
        if not self._token:
            self.login()
            return
        self._store_token(self._get(f"{API_PREFIX}/keepalive"))

    def ensure_authenticated(self) -> None:
        """Log in if we have no valid (unexpired) token."""
        if not self.token_valid:
            self.login()

    # --- generic request --------------------------------------------------
    def _request(
        self, method: str, path: str,
        params: Optional[dict[str, Any]] = None, *, _retry: bool = True,
    ) -> Any:
        self.ensure_authenticated()
        call_params = dict(params or {})
        call_params["token"] = self._token  # this API authenticates via ?token=
        url = self._url(path)
        resp = self.session.request(method, url, params=call_params, timeout=60)

        # The token may be rejected mid-session (expiry beyond the skew guard,
        # server-side revocation). This API reports that as 400 "Invalid token".
        if resp.status_code in (400, 401) and _retry:
            try:
                msg = resp.json().get("message", "")
            except ValueError:
                msg = ""
            if "token" in msg.lower():
                logger.info("Token rejected (%s); re-authenticating and retrying once.", msg)
                self._token = None
                self.login()
                return self._request(method, path, params, _retry=False)

        # Errors are surfaced as a JSON {"message": ...} body (note: url here has
        # no query string, so the token is never included in the exception text).
        if resp.status_code >= 400:
            try:
                message = resp.json().get("message", resp.text[:200])
            except ValueError:
                message = resp.text[:200]
            raise MeteologicaError(f"{method} {url} -> HTTP {resp.status_code}: {message}")

        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json() if "json" in resp.headers.get("content-type", "") else resp.text

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params)

    # --- data endpoints (confirmed against /api/v1/oas) ------------------
    def list_datasets(self) -> list[dict[str, Any]]:
        """Catalog of contents available to this account.

        Each item is {"id": int, "content_name": str, "path": str}. Cached per-process for a few
        minutes (the catalog changes rarely) so multiple consumers don't each trip the GetContents
        throttle on a cold render.
        """
        key = self.settings.base_url
        cached = _CONTENTS_CACHE.get(key)
        if cached and (time.monotonic() - cached[0]) < _CONTENTS_TTL:
            return cached[1]
        contents = self._get(f"{API_PREFIX}/contents")["contents"]
        _CONTENTS_CACHE[key] = (time.monotonic(), contents)
        return contents

    def search_contents(self, query: str) -> list[dict[str, Any]]:
        """Filter the catalog by case-insensitive substring of name or path."""
        q = query.lower()
        return [
            c for c in self.list_datasets()
            if q in c.get("content_name", "").lower() or q in c.get("path", "").lower()
        ]

    def get_content_data(
        self, content_id: int, *, update_id: Optional[str] = None,
        show_filename: bool = False,
    ) -> dict[str, Any]:
        """Latest data for a content (or a specific update_id).

        Returns {content_id, content_name, data: [row, ...], issue_date, timezone,
        unit, update_id}. Row values are strings; convert at a higher layer.
        """
        params: dict[str, Any] = {}
        if update_id is not None:
            params["update_id"] = update_id
        if show_filename:
            params["show_filename"] = "true"
        return self._get(f"{API_PREFIX}/contents/{content_id}/data", params)

    def get_historical_data(self, content_id: int, year: int, month: int) -> dict[str, Any]:
        """Historical data (one month) for a content.

        The API returns a ZIP of JSON file(s); we unzip and merge their `data` rows into
        a single /data-shaped dict. Raises MeteologicaError if the month isn't available.
        """
        self.ensure_authenticated()
        url = self._url(f"{API_PREFIX}/contents/{content_id}/historical_data/{year}/{month}")
        resp = self.session.get(url, params={"token": self._token}, timeout=120)
        if resp.status_code == 401:
            self._clear_token()
            self.login()
            resp = self.session.get(url, params={"token": self._token}, timeout=120)
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("message", resp.text[:200])
            except ValueError:
                msg = resp.text[:200]
            raise MeteologicaError(f"GET {url} -> HTTP {resp.status_code}: {msg}")
        if "zip" not in resp.headers.get("content-type", ""):
            return resp.json()
        merged: Optional[dict[str, Any]] = None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in sorted(n for n in zf.namelist() if n.endswith(".json")):
                obj = json.loads(zf.read(name))
                if merged is None:
                    merged = obj
                else:
                    merged.setdefault("data", []).extend(obj.get("data", []))
        return merged or {"content_id": content_id, "data": []}

    def get_updates(
        self, content_id: int, *, start_date: Optional[str] = None,
        end_date: Optional[str] = None, show_filename: bool = False,
    ) -> Any:
        """Updates available for a content. Dates are ISO 8601 'YYYY-MM-DDThh:mm:ssZ'."""
        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if show_filename:
            params["show_filename"] = "true"
        return self._get(f"{API_PREFIX}/contents/{content_id}/updates", params)

    def get_latest(self, *, seconds: Optional[int] = None) -> Any:
        """Contents updated recently (optionally within the last `seconds`)."""
        params = {} if seconds is None else {"seconds": seconds}
        return self._get(f"{API_PREFIX}/latest", params)


def _smoke_test(do_login: bool, do_probe: bool) -> None:
    settings = get_settings()
    print(f"Loaded credentials for user: {settings.username!r} | base_url: {settings.base_url}")
    if not (do_login or do_probe):
        print("(pass --login for a live auth check, or --probe to list ERCOT contents)")
        return
    client = MeteologicaClient(settings)
    client.login()
    print(f"Live login OK -> token {client.token_prefix} expires {client._token_expiration}")
    if do_probe:
        contents = client.list_datasets()
        print(f"\nCatalog: {len(contents)} contents available.")
        ercot = client.search_contents("ERCOT")
        print(f"ERCOT-related: {len(ercot)} contents. First few:")
        for c in ercot[:5]:
            print(f"  [{c['id']}] {c['content_name']}")


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    _smoke_test(do_login="--login" in args, do_probe="--probe" in args)
