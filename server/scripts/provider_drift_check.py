"""Provider drift check: do the live music services still answer in the shape our fakes use?

Compares the JSON keys of a live response with the fake response the tests rely on
(tests/fakes/providers.py), recursively. Run by hand or on a schedule, never in the PR suite:

    cd server && python scripts/provider_drift_check.py

Keyless providers (ListenBrainz, MusicBrainz) always run. Beatport and Tidal need a signed-in
account (skipped otherwise); tokens stay in memory and are never printed:

- Tidal: ``--tidal-login`` prints a link; open it on any device signed in to Tidal and approve
  (tidalapi's device login, the same one the app uses). Or set TIDAL_ACCESS_TOKEN.
- Beatport: set BEATPORT_USERNAME and BEATPORT_PASSWORD (plus the BEATPORT_CLIENT_ID and
  BEATPORT_AUTH_BASE_URL the app uses) and the check signs in with the app's own login flow.
  Or set BEATPORT_ACCESS_TOKEN.

Exit code 1 when a shape drifted or an endpoint is gone; a busy service (429/503) is
reported, not failed.

Without a Tidal token the next best signal is tidalapi itself (the community client that
reverse-engineers Tidal's API and whose parsers the Tidal fakes follow): a newer release on
PyPI is reported as "check", since it often follows an API change.
Beatport's OpenAPI schema needs a partner login (401), so Beatport has no keyless signal.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `tests` importable

from tests.fakes import (
    FakeHttp,  # noqa: E402
    providers,  # noqa: E402
)

UA = {"User-Agent": "WrzDJ drift check (https://github.com/wrzonance/WrzDJ)"}
RADIOHEAD = "a74b1b7f-71a5-4011-9441-d0b5e4122711"


def shape(value, depth: int = 0):
    """Keys and types, recursively; lists are described by their first item."""
    if depth > 6:
        return "..."
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def missing(fake, live, path: str = "") -> list[str]:
    """Keys the fake has that the live answer lacks (what our parsing could depend on)."""
    out = []
    if isinstance(fake, dict) and isinstance(live, dict):
        for k, v in fake.items():
            if k not in live:
                out.append(f"{path}.{k}" if path else k)
            else:
                out += missing(v, live[k], f"{path}.{k}" if path else k)
    elif isinstance(fake, list) and isinstance(live, list) and fake and live:
        out += missing(fake[0], live[0], f"{path}[0]")
    return out


def fake_body(register, method: str, url: str, request_body: bytes = b"{}"):
    http = FakeHttp()
    register(http)
    route = http.find(method, url)
    content, _ = route.payload(request_body)
    return json.loads(content)


def check(name, method, url, register, *, json_body=None, params=None, headers=None):
    body = json.dumps(json_body or {}).encode()
    fake = fake_body(register, method, url, body)
    try:
        r = httpx.request(
            method,
            url,
            json=json_body,
            params=params,
            headers={**UA, **(headers or {})},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        return name, "unreachable", type(exc).__name__
    if r.status_code in (429, 503):
        return name, "busy", f"HTTP {r.status_code}: try again later"
    if r.status_code == 404:
        return name, "DRIFT", "HTTP 404: the endpoint is gone or moved"
    if r.status_code >= 400:
        return name, "error", f"HTTP {r.status_code}"
    gaps = missing(shape(fake), shape(r.json()))
    return name, ("DRIFT" if gaps else "ok"), (f"missing in live: {gaps}" if gaps else "same keys")


def tidalapi_release() -> tuple[str, str, str]:
    """Installed tidalapi vs the newest on PyPI."""
    from importlib.metadata import version

    installed = version("tidalapi")
    try:
        r = httpx.get("https://pypi.org/pypi/tidalapi/json", headers=UA, timeout=15)
        latest = r.json()["info"]["version"]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return ("tidalapi release", "unknown", str(exc)[:60])
    if latest == installed:
        return ("tidalapi release", "ok", f"{installed} is the latest")
    return ("tidalapi release", "check", f"installed {installed}, PyPI {latest}")


def beatport_token() -> tuple[str | None, str]:
    """An access token from the env, or by the app's username/password login. (token, why-not)."""
    if token := os.environ.get("BEATPORT_ACCESS_TOKEN"):
        return token, ""
    user, password = os.environ.get("BEATPORT_USERNAME"), os.environ.get("BEATPORT_PASSWORD")
    if not (user and password):
        return None, "set BEATPORT_USERNAME + BEATPORT_PASSWORD (or BEATPORT_ACCESS_TOKEN)"
    from app.services.beatport import login_and_get_tokens

    try:
        return login_and_get_tokens(user, password)["access_token"], ""
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return None, f"login failed: {type(exc).__name__}"


def tidal_token(login: bool) -> tuple[str | None, int | None, str, str]:
    """(access token, user id, country, why-not). The device login waits for the approval."""
    if token := os.environ.get("TIDAL_ACCESS_TOKEN"):
        r = httpx.get(
            f"{providers.TIDAL_API}/sessions",
            headers={**UA, "Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if r.status_code != 200:
            return None, None, "", f"TIDAL_ACCESS_TOKEN rejected: HTTP {r.status_code}"
        return token, r.json().get("userId"), r.json().get("countryCode", "US"), ""
    if not login:
        return None, None, "", "run with --tidal-login (or set TIDAL_ACCESS_TOKEN)"
    import tidalapi

    session = tidalapi.Session()
    info, future = session.login_oauth()
    url = info.verification_uri_complete
    url = url if url.startswith("http") else f"https://{url}"
    print(f"Tidal: open {url} and approve (code {info.user_code}, {info.expires_in} s)", flush=True)
    try:
        future.result(timeout=info.expires_in)
    except Exception as exc:  # noqa: BLE001 - any failure means "no session"; report its type
        return None, None, "", f"device login not completed: {type(exc).__name__}"
    return session.access_token, session.user.id, session.country_code, ""


def tidal_checks(token: str, user_id: int, country: str) -> list[tuple[str, str, str]]:
    def register(http):
        providers.tidal_connected(http, user_id=user_id, country=country)

    kw = {"headers": {"Authorization": f"Bearer {token}"}, "params": {"countryCode": country}}
    base = providers.TIDAL_API
    return [
        check("tidal session", "GET", f"{base}/sessions", register, **kw),
        check("tidal user", "GET", f"{base}/users/{user_id}", register, **kw),
        check("tidal subscription", "GET", f"{base}/users/{user_id}/subscription", register, **kw),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Provider drift check (see the module docstring).")
    ap.add_argument("--tidal-login", action="store_true", help="sign in to Tidal with a link")
    args = ap.parse_args()
    results = [
        check(
            "listenbrainz popularity",
            "POST",
            providers.LISTENBRAINZ_POPULARITY,
            providers.listenbrainz_popular,
            json_body={"artist_mbids": [RADIOHEAD]},
        ),
        check(
            "musicbrainz artist search",
            "GET",
            f"{providers.MUSICBRAINZ_API}/artist/",
            providers.musicbrainz_no_match,
            params={"query": "artist:radiohead", "fmt": "json", "limit": "1"},
        ),
    ]
    bp, why = beatport_token()
    if bp:
        auth = {"Authorization": f"Bearer {bp}"}
        results.append(
            check(
                "beatport account",
                "GET",
                f"{providers.BEATPORT_API}/my/account/",
                providers.beatport_up,
                headers=auth,
            )
        )
        results.append(
            check(
                "beatport catalog search",
                "GET",
                f"{providers.BEATPORT_API}/catalog/search/",
                providers.beatport_up,
                params={"q": "Midnight City", "per_page": 1, "type": "tracks"},
                headers=auth,
            )
        )
    else:
        results.append(("beatport", "skipped", why))
    tidal, tidal_user, country, why = tidal_token(args.tidal_login)
    if tidal:
        results += tidal_checks(tidal, tidal_user, country)
    else:
        results.append(("tidal", "skipped", why))
    results.append(tidalapi_release())
    for name, status, detail in results:
        print(f"{status:12s} {name:28s} {detail}")
    return 1 if any(s == "DRIFT" for _, s, _ in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
