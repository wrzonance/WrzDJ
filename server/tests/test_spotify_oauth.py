"""Spotify user OAuth state and encrypted-token lifecycle tests."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text

from app.services import spotify_oauth


def _settings(monkeypatch):
    settings = SimpleNamespace(
        spotify_client_id="client-id",
        spotify_client_secret="client-secret",
        spotify_redirect_uri="https://api.example.test/api/spotify/auth/callback",
        public_url="https://app.example.test",
    )
    monkeypatch.setattr(spotify_oauth, "get_settings", lambda: settings)
    return settings


def test_authorization_url_persists_one_time_state(db, test_user, monkeypatch):
    _settings(monkeypatch)

    url = spotify_oauth.authorization_url(db, test_user)
    params = parse_qs(urlparse(url).query)

    assert url.startswith("https://accounts.spotify.com/authorize?")
    assert params["client_id"] == ["client-id"]
    assert {"playlist-modify-private", "user-library-modify"}.issubset(params["scope"][0].split())
    assert test_user.spotify_oauth_state == params["state"][0]
    assert params["state"][0].startswith(f"{test_user.id}.")


def test_exchange_accepts_all_required_scopes_regardless_of_order(monkeypatch):
    _settings(monkeypatch)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "access_token": "access",
                "refresh_token": "refresh",
                "scope": "user-library-modify playlist-modify-private",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(spotify_oauth.httpx, "Client", FakeClient)

    result = spotify_oauth._exchange_code("code")

    assert result["access_token"] == "access"


def test_finish_authorization_rejects_mismatched_state(db, test_user, monkeypatch):
    _settings(monkeypatch)
    monkeypatch.setattr(spotify_oauth, "time", lambda: 1000)
    test_user.spotify_oauth_state = "another-state"
    db.commit()
    monkeypatch.setattr(
        spotify_oauth, "_exchange_code", lambda code: (_ for _ in ()).throw(AssertionError())
    )

    with pytest.raises(spotify_oauth.SpotifyOAuthError, match="Invalid Spotify authorization"):
        spotify_oauth.finish_authorization(db, f"{test_user.id}.1000.random", "code")


@pytest.mark.parametrize(
    "state",
    ["2147483648.1000.nonce", "1.1000.nønce"],
)
def test_finish_authorization_rejects_malformed_state_without_database_errors(
    db, test_user, monkeypatch, state
):
    _settings(monkeypatch)
    with pytest.raises(spotify_oauth.SpotifyOAuthError, match="Invalid Spotify authorization"):
        spotify_oauth.finish_authorization(db, state, "code")


def test_failed_refresh_clears_stale_credentials(db, test_user, monkeypatch):
    import httpx

    _settings(monkeypatch)
    test_user.spotify_access_token = "stale-access"
    test_user.spotify_refresh_token = "revoked-refresh"
    from datetime import UTC, datetime, timedelta

    test_user.spotify_token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    class FailedClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(spotify_oauth.httpx, "Client", FailedClient)

    assert not spotify_oauth.refresh_access_token(db, test_user)
    assert test_user.spotify_access_token is None
    assert test_user.spotify_refresh_token is None


def test_finish_authorization_saves_encrypted_tokens_and_clears_state(db, test_user, monkeypatch):
    _settings(monkeypatch)
    state = f"{test_user.id}.9999999999.random"  # patched clock below keeps state current
    monkeypatch.setattr(spotify_oauth, "time", lambda: 9999999999)
    test_user.spotify_oauth_state = state
    db.commit()
    monkeypatch.setattr(
        spotify_oauth,
        "_exchange_code",
        lambda code: {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 1800,
        },
    )

    linked_user = spotify_oauth.finish_authorization(db, state, "one-time-code")

    assert linked_user.spotify_access_token == "new-access"
    assert linked_user.spotify_refresh_token == "new-refresh"
    assert linked_user.spotify_oauth_state is None
    raw_value = db.execute(
        text("SELECT spotify_access_token FROM users WHERE id = :id"), {"id": test_user.id}
    ).scalar_one()
    assert raw_value != "new-access"


def test_disconnect_clears_credentials_and_pending_state(db, test_user):
    test_user.spotify_access_token = "access"
    test_user.spotify_refresh_token = "refresh"
    test_user.spotify_oauth_state = "state"
    db.commit()

    spotify_oauth.disconnect(db, test_user)

    assert test_user.spotify_access_token is None
    assert test_user.spotify_refresh_token is None
    assert test_user.spotify_oauth_state is None
