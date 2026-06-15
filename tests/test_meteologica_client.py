"""Tests for the Meteologica API client auth flow (all network calls mocked)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from src.config import Settings
from src.meteologica_client import (
    _EXPIRY_SKEW_SECONDS,
    AuthError,
    MeteologicaClient,
    _parse_expiration,
)

SETTINGS = Settings(username="u", password="p", base_url="https://example.com")


def make_client() -> MeteologicaClient:
    # token_cache=None keeps unit tests hermetic (no on-disk token reuse).
    return MeteologicaClient(SETTINGS, token_cache=None)


def fake_response(
    *, json_data: dict | None = None, status: int = 200, content: bytes = b"{}",
    ct: str = "application/json", raise_json: bool = False,
) -> mock.Mock:
    m = mock.Mock()
    m.status_code = status
    m.content = content
    m.headers = {"content-type": ct}
    m.text = "<html>not json</html>" if raise_json else (content.decode() or "")
    if raise_json:
        m.json.side_effect = ValueError("no json")
    else:
        m.json.return_value = json_data
    return m


# --- _parse_expiration ----------------------------------------------------
def test_parse_expiration_z_suffix() -> None:
    assert _parse_expiration("2026-06-09T23:25:23Z") == datetime(
        2026, 6, 9, 23, 25, 23, tzinfo=timezone.utc
    )


def test_parse_expiration_empty_returns_none() -> None:
    assert _parse_expiration("") is None


def test_parse_expiration_malformed_returns_none() -> None:
    assert _parse_expiration("not-a-date") is None


# --- token_valid ----------------------------------------------------------
def test_token_valid_false_without_token() -> None:
    assert make_client().token_valid is False


def test_token_valid_true_for_future_expiry() -> None:
    c = make_client()
    c._token = "x"
    c._token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
    assert c.token_valid is True


def test_token_valid_false_when_expired() -> None:
    c = make_client()
    c._token = "x"
    c._token_expiration = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert c.token_valid is False


def test_token_valid_false_within_skew_window() -> None:
    c = make_client()
    c._token = "x"
    c._token_expiration = datetime.now(timezone.utc) + timedelta(
        seconds=_EXPIRY_SKEW_SECONDS - 5
    )
    assert c.token_valid is False


def test_token_valid_true_when_expiry_unknown() -> None:
    c = make_client()
    c._token = "x"
    c._token_expiration = None
    assert c.token_valid is True


# --- token_prefix ---------------------------------------------------------
def test_token_prefix_never_reveals_full_token() -> None:
    c = make_client()
    assert c.token_prefix == "<none>"
    c._token = "eyJhbGciOiJIUzI1NiJ9.payloadsecret"
    assert c.token_prefix == "eyJhbGci…"
    assert "payloadsecret" not in c.token_prefix


# --- login ----------------------------------------------------------------
def test_login_success_stores_token() -> None:
    c = make_client()
    resp = fake_response(
        json_data={"token": "abc.def.ghi", "expiration_date": "2026-06-09T23:25:23Z"}
    )
    with mock.patch.object(c.session, "post", return_value=resp) as post:
        c.login()
    assert c._token == "abc.def.ghi"
    # This API authenticates via ?token=, NOT an Authorization header.
    assert "Authorization" not in c.session.headers
    assert c._token_expiration == datetime(2026, 6, 9, 23, 25, 23, tzinfo=timezone.utc)
    _, kwargs = post.call_args
    assert kwargs["json"] == {"user": "u", "password": "p"}


def test_login_message_body_raises_autherror() -> None:
    c = make_client()
    resp = fake_response(json_data={"message": "Invalid credentials"})
    with mock.patch.object(c.session, "post", return_value=resp):
        with pytest.raises(AuthError, match="Invalid credentials"):
            c.login()


def test_login_non_json_raises_autherror() -> None:
    c = make_client()
    resp = fake_response(raise_json=True)
    with mock.patch.object(c.session, "post", return_value=resp):
        with pytest.raises(AuthError):
            c.login()


def test_login_missing_token_raises_autherror() -> None:
    c = make_client()
    resp = fake_response(json_data={"expiration_date": "2026-06-09T23:25:23Z"})
    with mock.patch.object(c.session, "post", return_value=resp):
        with pytest.raises(AuthError):
            c.login()


# --- _request retry-on-401 ------------------------------------------------
def test_request_reauthenticates_once_on_401() -> None:
    c = make_client()
    c._token = "stale"
    c._token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)

    def fake_login() -> None:  # simulate a successful re-login
        c._token = "fresh"
        c._token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
        c.session.headers["Authorization"] = "Bearer fresh"

    # Expired token is reported as 400 {"message": "Error. Invalid token"}.
    first = fake_response(status=400, json_data={"message": "Error. Invalid token"})
    second = fake_response(json_data={"ok": True})
    with mock.patch.object(c.session, "request", side_effect=[first, second]) as req, \
            mock.patch.object(c, "login", side_effect=fake_login) as login:
        out = c._get("/api/v1/whatever")

    assert out == {"ok": True}
    assert req.call_count == 2
    assert login.call_count == 1


def test_request_raises_with_api_message_on_error() -> None:
    c = make_client()
    c._token = "tok"
    c._token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
    resp = fake_response(status=400, json_data={"message": "no matching operation was found"})
    with mock.patch.object(c.session, "request", return_value=resp):
        with pytest.raises(Exception, match="no matching operation was found"):
            c._get("/api/v1/bogus")


def test_token_cache_reused_without_login(tmp_path: Path) -> None:
    cache = tmp_path / "tok.json"
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    cache.write_text(json.dumps({"token": "cached-token", "expiration_date": future}))
    c = MeteologicaClient(SETTINGS, token_cache=cache)
    assert c._token == "cached-token"
    assert c.token_valid
    # A cached, valid token must NOT trigger a login (this is the rate-limit fix).
    with mock.patch.object(c, "login", side_effect=AssertionError("should not log in")):
        c.ensure_authenticated()


def test_expired_token_cache_is_discarded(tmp_path: Path) -> None:
    cache = tmp_path / "tok.json"
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    cache.write_text(json.dumps({"token": "stale", "expiration_date": past}))
    c = MeteologicaClient(SETTINGS, token_cache=cache)
    assert c._token is None  # expired cache ignored
    assert not c.token_valid


def test_login_writes_token_cache(tmp_path: Path) -> None:
    cache = tmp_path / "tok.json"
    c = MeteologicaClient(SETTINGS, token_cache=cache)
    resp = fake_response(json_data={"token": "fresh", "expiration_date": "2026-06-09T23:25:23Z"})
    with mock.patch.object(c.session, "post", return_value=resp):
        c.login()
    assert json.loads(cache.read_text())["token"] == "fresh"


def test_request_returns_none_on_204() -> None:
    c = make_client()
    c._token = "tok"
    c._token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
    resp = fake_response(status=204, content=b"")
    with mock.patch.object(c.session, "request", return_value=resp):
        assert c._get("/api/v1/empty") is None


def test_request_injects_token_query_param() -> None:
    c = make_client()
    c._token = "tok123"
    c._token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
    resp = fake_response(json_data={"ok": True})
    with mock.patch.object(c.session, "request", return_value=resp) as req:
        c._get("/api/v1/contents", {"foo": "bar"})
    _, kwargs = req.call_args
    assert kwargs["params"] == {"foo": "bar", "token": "tok123"}
    # The bare URL (used in error messages) must not carry the token.
    assert "token" not in req.call_args.args[1]


# --- data endpoints -------------------------------------------------------
def test_list_datasets_unwraps_contents() -> None:
    c = make_client()
    c._token = "tok"
    c._token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
    catalog = {"contents": [{"id": 1, "content_name": "A", "path": "p"}]}
    with mock.patch.object(c, "_get", return_value=catalog) as get:
        out = c.list_datasets()
    assert out == catalog["contents"]
    get.assert_called_once_with("/api/v1/contents")


def test_search_contents_filters_by_name_and_path() -> None:
    c = make_client()
    items = [
        {"id": 1, "content_name": "USA ERCOT wind", "path": "NorthAmerica/USA/ERCOT/Wind"},
        {"id": 2, "content_name": "Spain solar", "path": "Europe/Spain/Solar"},
    ]
    with mock.patch.object(c, "list_datasets", return_value=items):
        assert [c_["id"] for c_ in c.search_contents("ercot")] == [1]


def test_get_content_data_builds_path_and_params() -> None:
    c = make_client()
    with mock.patch.object(c, "_get", return_value={"data": []}) as get:
        c.get_content_data(5212, update_id="202606090000", show_filename=True)
    get.assert_called_once_with(
        "/api/v1/contents/5212/data",
        {"update_id": "202606090000", "show_filename": "true"},
    )


def test_get_historical_data_hits_path_and_returns_json() -> None:
    c = make_client()
    c._token = "tok"
    c._token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
    resp = fake_response(json_data={"content_id": 5212, "data": [{"x": 1}]})  # non-zip -> JSON path
    with mock.patch.object(c.session, "get", return_value=resp) as g:
        out = c.get_historical_data(5212, 2026, 5)
    assert out == {"content_id": 5212, "data": [{"x": 1}]}
    assert g.call_args.args[0].endswith("/api/v1/contents/5212/historical_data/2026/5")
