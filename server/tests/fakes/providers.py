"""Provider fakes: realistic responses for the music services the app calls.

Shapes follow what the app (and tidalapi) parse; each function registers the "service is up,
answer is ordinary" case. Tests layer bad days on top with ``fake_http.add(...)`` (it matches
newest first): status=429/401/500, or raises="timeout".
"""

from __future__ import annotations

import json

from tests.fakes import FakeHttp

TIDAL_API = "https://api.tidal.com/v1"
TIDAL_USER_ID = 424242


def tidal_connected(http: FakeHttp, user_id: int = TIDAL_USER_ID, country: str = "US") -> None:
    """A Tidal account whose stored tokens are valid (tidalapi 0.8 session load + check_login)."""
    http.add(
        "GET",
        f"{TIDAL_API}/sessions",
        json={"sessionId": "fake-session", "userId": user_id, "countryCode": country},
    )
    http.add(
        "GET",
        f"{TIDAL_API}/users/{user_id}",
        json={
            "id": user_id,
            "username": "dj_demo",
            "email": "dj_demo@wrzdj.test",
            "firstName": "Demo",
            "lastName": "DJ",
            "picture": None,
        },
    )
    http.add(
        "GET",
        f"{TIDAL_API}/users/{user_id}/subscription",
        json={"type": "PREMIUM", "status": "ACTIVE"},
    )


def tidal_down(http: FakeHttp) -> None:
    """Tidal refuses connections (API and auth): the app's "Tidal unavailable" path."""
    http.add("GET", "https://api.tidal.com/*", raises="connect")
    http.add("POST", "https://api.tidal.com/*", raises="connect")
    http.add("POST", "https://auth.tidal.com/*", raises="connect")


BEATPORT_API = "https://api.beatport.com/v4"
BEATPORT_AUTH = "https://account.beatport.com"


def beatport_up(http: FakeHttp, streaming: bool = True) -> None:
    """Beatport account, token revoke and an empty catalogue search."""
    http.add(
        "GET",
        f"{BEATPORT_API}/my/account/",
        json={
            "id": 7,
            "username": "dj_demo",
            "preferences": {"streaming_audio_format_id": 1 if streaming else None},
        },
    )
    http.add("POST", f"{BEATPORT_AUTH}/o/revoke_token/", status=200, body=b"")
    http.add("GET", f"{BEATPORT_API}/catalog/search/", json={"tracks": [], "releases": []})


LISTENBRAINZ_POPULARITY = "https://api.listenbrainz.org/1/popularity/artist"


def listenbrainz_popular(http: FakeHttp, users: int = 5000, listens: int = 250_000) -> None:
    """Every requested artist is popular (passes the popularity gate). Echoes the MBIDs sent."""

    def respond(body: bytes):
        mbids = json.loads(body or b"{}").get("artist_mbids", [])
        return [
            {"artist_mbid": m, "total_listen_count": listens, "total_user_count": users}
            for m in mbids
        ]

    http.add("POST", LISTENBRAINZ_POPULARITY, json=respond)


MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"


def musicbrainz_no_match(http: FakeHttp) -> None:
    """MusicBrainz is up but finds no artist (genre lookup falls back)."""
    http.add(
        "GET",
        f"{MUSICBRAINZ_API}/artist/*",
        json={"created": "2026-10-25T00:00:00Z", "count": 0, "artists": []},
    )
