"""One-off probe to discover the Meteologica 'API markets' auth flow + endpoints.

Read-only and LOCKOUT-SAFE: it inspects the login page, checks for a public
machine-readable API spec, and attempts AT MOST ONE login (using the field names
actually present in the form). It does not modify the account.

The sandbox cannot reach api-markets.meteologica.com (network allowlist), so run
this on your own machine:

    ./setup.sh && source dash_env/bin/activate
    python -m src.probe_api

Then paste the output back so the real auth flow + endpoints can be wired into
meteologica_client.py.
"""
from __future__ import annotations

import re

import requests

from .config import get_settings


def show(label: str, resp: requests.Response, snippet: int = 400) -> None:
    ct = resp.headers.get("content-type", "")
    body = resp.text or ""
    print(f"\n[{label}] {resp.request.method} {resp.url}")
    print(f"  status={resp.status_code}  content-type={ct}  len={len(body)}")
    s = body.strip().replace("\n", " ")
    if s:
        print(f"  snippet: {s[:snippet]}")


def find_form_fields(html: str) -> list[str]:
    return re.findall(r'<input[^>]*name=["\']([^"\']+)["\']', html, flags=re.I)


def find_form_action(html: str) -> str | None:
    m = re.search(r'<form[^>]*action=["\']([^"\']+)["\']', html, flags=re.I)
    return m.group(1) if m else None


def probe_specs(session: requests.Session, base: str, label: str) -> None:
    print(f"\n=== {label}: probing machine-readable spec locations ===")
    for path in (
        "/openapi.json", "/swagger.json", "/api/openapi.json",
        "/docs/openapi.json", "/api-docs", "/api/docs", "/docs/api",
        "/api/v1", "/api",
    ):
        try:
            r = session.get(f"{base}{path}", timeout=20, allow_redirects=True)
        except requests.RequestException as e:
            print(f"  {path} -> ERROR {e}")
            continue
        ct = r.headers.get("content-type", "")
        print(f"  {path} -> {r.status_code} {ct} len={len(r.text)}")
        if "json" in ct and r.status_code == 200:
            show(f"SPEC {path}", r, snippet=600)


def main() -> None:
    settings = get_settings()
    base = settings.base_url
    print(f"Base URL: {base}")
    print(f"User: {settings.username!r}")  # username only; the password is never printed

    s = requests.Session()
    s.headers.update({"User-Agent": "ercot-monitor-probe/0.1"})

    # 1) Inspect the login page: form action, field names, CSRF, cookies.
    try:
        r = s.get(f"{base}/login", timeout=20)
    except requests.RequestException as e:
        print(f"GET /login failed: {e}")
        return
    show("GET /login", r)
    fields = find_form_fields(r.text)
    action = find_form_action(r.text)
    print(f"  form action: {action}")
    print(f"  form fields: {fields}")
    print(f"  cookies: {s.cookies.get_dict()}")

    # 2) Public spec without auth?
    probe_specs(s, base, "unauthenticated")

    # 3) ONE form-driven login attempt, only if we can identify the fields.
    user_field = next((f for f in fields if re.search(r"user|name|login|email", f, re.I)), None)
    pass_field = next((f for f in fields if re.search(r"pass", f, re.I)), None)
    if not (user_field and pass_field):
        print("\nCould not identify login fields automatically; stopping before any login attempt.")
        print("Paste the form fields above and we'll set the exact field names.")
        return

    payload = {user_field: settings.username, pass_field: settings.password}
    # carry hidden fields (e.g. CSRF tokens) through unchanged
    for f in fields:
        if f not in payload:
            m = re.search(
                rf'<input[^>]*name=["\']{re.escape(f)}["\'][^>]*value=["\']([^"\']*)["\']',
                r.text, flags=re.I,
            )
            payload[f] = m.group(1) if m else ""
    post_url = action if (action and action.startswith("http")) else f"{base}{action or '/login'}"
    print(f"\n=== single login attempt -> POST {post_url} (fields: {list(payload)}) ===")
    try:
        lr = s.post(post_url, data=payload, timeout=20, allow_redirects=True)
    except requests.RequestException as e:
        print(f"login POST failed: {e}")
        return
    show("POST login", lr)
    print(f"  cookies after login: {s.cookies.get_dict()}")

    # 4) If login looks successful, probe specs/endpoints again, authenticated.
    if lr.status_code in (200, 302) and not lr.url.rstrip("/").endswith("/login"):
        probe_specs(s, base, "authenticated")
        for path in ("/docs", "/docs/api", "/dashboard", "/datasets", "/products"):
            try:
                r2 = s.get(f"{base}{path}", timeout=20)
                print(f"  GET {path} -> {r2.status_code} {r2.headers.get('content-type','')} len={len(r2.text)}")
            except requests.RequestException as e:
                print(f"  GET {path} -> ERROR {e}")
    else:
        print("\nLogin did not clearly succeed (still on /login). Check field names / CSRF handling.")


if __name__ == "__main__":
    main()
