"""HTTP boundary tests for Spotify linking."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.services import spotify_oauth


def _configure_spotify(monkeypatch):
    settings = SimpleNamespace(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        spotify_redirect_uri="http://api.example.test/api/spotify/auth/callback",
        public_url="https://app.example.test",
    )
    monkeypatch.setattr("app.api.spotify.get_settings", lambda: settings)
    monkeypatch.setattr(spotify_oauth, "get_settings", lambda: settings)


def test_auth_start_returns_provider_url_and_persists_state(
    client, auth_headers, test_user, db, monkeypatch
):
    _configure_spotify(monkeypatch)

    response = client.post("/api/spotify/auth/start", headers=auth_headers)

    assert response.status_code == 200
    params = parse_qs(urlparse(response.json()["authorization_url"]).query)
    assert {"playlist-modify-private", "user-library-modify"}.issubset(params["scope"][0].split())
    assert test_user.spotify_oauth_state == params["state"][0]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/spotify/auth/callback" in cookie


def test_status_reports_unlinked_without_expiry(client, auth_headers, monkeypatch):
    _configure_spotify(monkeypatch)

    response = client.get("/api/spotify/status", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"configured": True, "linked": False, "expires_at": None}


def test_callback_rejects_forged_state(client, monkeypatch):
    _configure_spotify(monkeypatch)
    monkeypatch.setattr(spotify_oauth, "time", lambda: 1000)

    response = client.get(
        "/api/spotify/auth/callback",
        params={"state": "1.1000.forged", "code": "authorization-code"},
    )

    assert response.status_code == 400


def test_callback_requires_the_browser_cookie_set_at_auth_start(client, monkeypatch):
    _configure_spotify(monkeypatch)
    response = client.get(
        "/api/spotify/auth/callback",
        params={"state": "1.1000.forged", "code": "authorization-code"},
    )

    assert response.status_code == 400
    assert "state" in response.json()["detail"].lower()


def test_callback_accepts_matching_browser_cookie_and_clears_it(client, auth_headers, monkeypatch):
    _configure_spotify(monkeypatch)
    monkeypatch.setattr("app.api.spotify.finish_authorization", lambda db, state, code: None)
    started = client.post("/api/spotify/auth/start", headers=auth_headers)
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    client.cookies.set("wrzdj_spotify_oauth_state", state, path="/api/spotify/auth/callback")

    response = client.get(
        "/api/spotify/auth/callback",
        params={"state": state, "code": "authorization-code"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "Max-Age=0" in response.headers["set-cookie"]
