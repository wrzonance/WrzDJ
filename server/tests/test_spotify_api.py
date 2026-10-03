"""HTTP boundary tests for Spotify linking."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.services import spotify_oauth


def _configure_spotify(monkeypatch):
    settings = SimpleNamespace(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        spotify_redirect_uri="https://api.example.test/api/spotify/auth/callback",
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
    assert params["scope"] == ["playlist-modify-private"]
    assert test_user.spotify_oauth_state == params["state"][0]


def test_callback_rejects_forged_state(client, monkeypatch):
    _configure_spotify(monkeypatch)
    monkeypatch.setattr(spotify_oauth, "time", lambda: 1000)

    response = client.get(
        "/api/spotify/auth/callback",
        params={"state": "1.1000.forged", "code": "authorization-code"},
    )

    assert response.status_code == 400
