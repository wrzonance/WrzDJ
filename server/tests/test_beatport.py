"""Tests for Beatport service layer."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.beatport import (
    BEATPORT_API_BASE,
    DEFAULT_TOKEN_EXPIRY,
    _authorize_url,
    _parse_duration,
    _refresh_token_if_needed,
    _token_url,
    add_tracks_to_beatport_playlist,
    create_beatport_playlist,
    disconnect_beatport,
    fetch_subscription_type,
    get_beatport_track,
    get_playlist_tracks,
    list_user_playlists,
    login_and_get_tokens,
    manual_link_beatport_track,
    save_tokens,
    search_beatport_tracks,
)


@pytest.fixture
def beatport_user(db: Session) -> User:
    """User with Beatport tokens."""
    user = User(
        username="beatport_user",
        password_hash=get_password_hash("testpassword123"),
        beatport_access_token="bp_access_token_123",
        beatport_refresh_token="bp_refresh_token_456",
        beatport_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def beatport_user_expired(db: Session) -> User:
    """User with expired Beatport tokens."""
    user = User(
        username="beatport_expired",
        password_hash=get_password_hash("testpassword123"),
        beatport_access_token="bp_expired_token",
        beatport_refresh_token="bp_refresh_token_789",
        beatport_token_expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def beatport_user_no_token(db: Session) -> User:
    """User without Beatport tokens."""
    user = User(
        username="beatport_notoken",
        password_hash=get_password_hash("testpassword123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


MOCK_SEARCH_RESPONSE = {
    "tracks": [
        {
            "id": 12345,
            "name": "Strobe",
            "slug": "strobe",
            "mix_name": "Original Mix",
            "artists": [{"name": "deadmau5"}],
            "label": {"name": "mau5trap"},
            "genre": {"name": "Progressive House"},
            "bpm": 128,
            "key": {"name": "A min"},
            "length": "10:33",
            "image": {"uri": "https://geo-media.beatport.com/image/12345.jpg"},
            "new_release_date": "2009-09-14",
        }
    ]
}


class TestSearchBeatportTracks:
    @patch("app.services.beatport.httpx.Client")
    def test_search_success(self, mock_client_cls, db: Session, beatport_user: User):
        """Successful search returns parsed results."""
        mock_response = MagicMock()
        mock_response.json.return_value = MOCK_SEARCH_RESPONSE
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        results = search_beatport_tracks(db, beatport_user, "deadmau5 Strobe")

        assert len(results) == 1
        assert results[0].track_id == "12345"
        assert results[0].title == "Strobe"
        assert results[0].artist == "deadmau5"
        assert results[0].mix_name == "Original Mix"
        assert results[0].label == "mau5trap"
        assert results[0].genre == "Progressive House"
        assert results[0].bpm == 128
        assert results[0].key == "A min"
        assert results[0].duration_seconds == 633
        assert "beatport.com/track/strobe/12345" in results[0].beatport_url

    @patch("app.services.beatport.httpx.Client")
    def test_search_uses_catalog_search_url(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """Search uses the v4 catalog search endpoint with type=tracks."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"tracks": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        search_beatport_tracks(db, beatport_user, "test")

        call_args = mock_client.get.call_args
        assert call_args.args[0] == f"{BEATPORT_API_BASE}/catalog/search/"
        assert call_args.kwargs["params"]["type"] == "tracks"

    @patch("app.services.beatport.httpx.Client")
    def test_search_empty(self, mock_client_cls, db: Session, beatport_user: User):
        """Empty search results return empty list."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"tracks": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        results = search_beatport_tracks(db, beatport_user, "nonexistent track xyz")
        assert results == []

    def test_search_no_token(self, db: Session, beatport_user_no_token: User):
        """No token returns empty list without making API calls."""
        results = search_beatport_tracks(db, beatport_user_no_token, "deadmau5 Strobe")
        assert results == []


class TestBeatportUrlFormat:
    def test_url_format(self):
        """Beatport URL has correct format."""
        from app.services.beatport import BEATPORT_TRACK_URL

        url = BEATPORT_TRACK_URL.format(slug="strobe", track_id="12345")
        assert url == "https://www.beatport.com/track/strobe/12345"


class TestDisconnect:
    def test_disconnect_clears_tokens(self, db: Session, beatport_user: User):
        """Disconnect clears all Beatport token columns."""
        assert beatport_user.beatport_access_token is not None

        disconnect_beatport(db, beatport_user)

        db.refresh(beatport_user)
        assert beatport_user.beatport_access_token is None
        assert beatport_user.beatport_refresh_token is None
        assert beatport_user.beatport_token_expires_at is None


class TestSearchIncludesMixName:
    @patch("app.services.beatport.httpx.Client")
    def test_mix_name_captured(self, mock_client_cls, db: Session, beatport_user: User):
        """Beatport-specific mix_name field is captured."""
        response_data = {
            "tracks": [
                {
                    "id": 99999,
                    "name": "Levels",
                    "slug": "levels",
                    "mix_name": "Extended Mix",
                    "artists": [{"name": "Avicii"}],
                    "length": "6:30",
                },
            ]
        }
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        results = search_beatport_tracks(db, beatport_user, "Avicii Levels")
        assert results[0].mix_name == "Extended Mix"


class TestTokenRefresh:
    @patch("app.services.beatport.httpx.Client")
    def test_refresh_on_expiry(self, mock_client_cls, db: Session, beatport_user_expired: User):
        """Expired token triggers refresh, then search succeeds."""
        refresh_response = MagicMock()
        refresh_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 600,
        }
        refresh_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = refresh_response
        mock_client_cls.return_value = mock_client

        result = _refresh_token_if_needed(db, beatport_user_expired)

        assert result is True
        db.refresh(beatport_user_expired)
        assert beatport_user_expired.beatport_access_token == "new_access_token"
        assert beatport_user_expired.beatport_refresh_token == "new_refresh_token"
        # SQLite returns naive datetimes, so compare without timezone
        expires = beatport_user_expired.beatport_token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        assert expires > datetime.now(UTC)


class TestParseDuration:
    def test_minutes_seconds(self):
        assert _parse_duration("5:30") == 330

    def test_hours_minutes_seconds(self):
        assert _parse_duration("1:05:30") == 3930

    def test_none(self):
        assert _parse_duration(None) is None

    def test_invalid(self):
        assert _parse_duration("invalid") is None


class TestCorrectApiUrls:
    @patch("app.services.beatport.get_settings")
    def test_authorize_url_uses_configured_base(self, mock_settings):
        """Authorize URL uses the configured beatport_auth_base_url."""
        mock_settings.return_value.beatport_auth_base_url = "https://account.beatport.com"
        assert _authorize_url() == "https://account.beatport.com/o/authorize/"

    @patch("app.services.beatport.get_settings")
    def test_token_url_uses_configured_base(self, mock_settings):
        """Token URL uses the configured beatport_auth_base_url."""
        mock_settings.return_value.beatport_auth_base_url = "https://account.beatport.com"
        assert _token_url() == "https://account.beatport.com/o/token/"

    @patch("app.services.beatport.get_settings")
    def test_v4_auth_base_override(self, mock_settings):
        """Auth URLs can be overridden to v4 path for public client testing."""
        mock_settings.return_value.beatport_auth_base_url = "https://api.beatport.com/v4/auth"
        assert _authorize_url() == "https://api.beatport.com/v4/auth/o/authorize/"
        assert _token_url() == "https://api.beatport.com/v4/auth/o/token/"


class TestLoginAndGetTokens:
    @patch("app.services.beatport.get_settings")
    @patch("app.services.beatport.httpx.Client")
    def test_login_success(self, mock_client_cls, mock_settings):
        """Successful login returns token data."""
        mock_settings.return_value.beatport_client_id = "test-client-id"
        mock_settings.return_value.beatport_redirect_uri = "https://example.com/callback"
        mock_settings.return_value.beatport_auth_base_url = "https://api.beatport.com/v4/auth"

        login_response = MagicMock()
        login_response.json.return_value = {"username": "dj_test", "email": "dj@test.com"}
        login_response.raise_for_status = MagicMock()

        authorize_response = MagicMock()
        authorize_response.status_code = 302
        authorize_response.headers = {"location": "/callback?code=auth-code-xyz"}

        token_response = MagicMock()
        token_response.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 600,
        }
        token_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [login_response, token_response]
        mock_client.get.return_value = authorize_response
        mock_client_cls.return_value = mock_client

        result = login_and_get_tokens("dj_test", "password123")

        assert result["access_token"] == "new-access"
        assert result["refresh_token"] == "new-refresh"

    @patch("app.services.beatport.get_settings")
    @patch("app.services.beatport.httpx.Client")
    def test_login_invalid_credentials(self, mock_client_cls, mock_settings):
        """Invalid credentials raises HTTPStatusError."""
        mock_settings.return_value.beatport_client_id = "test-client-id"
        mock_settings.return_value.beatport_redirect_uri = "https://example.com/callback"
        mock_settings.return_value.beatport_auth_base_url = "https://api.beatport.com/v4/auth"

        login_response = MagicMock()
        login_response.status_code = 401
        login_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=login_response
        )

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = login_response
        mock_client_cls.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            login_and_get_tokens("baduser", "badpass")

    @patch("app.services.beatport.get_settings")
    @patch("app.services.beatport.httpx.Client")
    def test_login_missing_fields_raises_value_error(self, mock_client_cls, mock_settings):
        """Login response without username/email fields raises ValueError."""
        mock_settings.return_value.beatport_client_id = "test-client-id"
        mock_settings.return_value.beatport_redirect_uri = "https://example.com/callback"
        mock_settings.return_value.beatport_auth_base_url = "https://api.beatport.com/v4/auth"

        login_response = MagicMock()
        login_response.json.return_value = {"status": "ok"}  # Missing username/email
        login_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = login_response
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="Invalid Beatport credentials"):
            login_and_get_tokens("user", "pass")

    @patch("app.services.beatport.get_settings")
    @patch("app.services.beatport.httpx.Client")
    def test_login_authorize_not_redirect_raises_value_error(self, mock_client_cls, mock_settings):
        """Non-redirect response from authorize raises ValueError."""
        mock_settings.return_value.beatport_client_id = "test-client-id"
        mock_settings.return_value.beatport_redirect_uri = "https://example.com/callback"
        mock_settings.return_value.beatport_auth_base_url = "https://api.beatport.com/v4/auth"

        login_response = MagicMock()
        login_response.json.return_value = {"username": "dj", "email": "dj@test.com"}
        login_response.raise_for_status = MagicMock()

        authorize_response = MagicMock()
        authorize_response.status_code = 200
        authorize_response.text = "Not a redirect"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = login_response
        mock_client.get.return_value = authorize_response
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="Expected redirect"):
            login_and_get_tokens("dj", "pass")

    @patch("app.services.beatport.get_settings")
    @patch("app.services.beatport.httpx.Client")
    def test_login_no_code_in_redirect_raises_value_error(self, mock_client_cls, mock_settings):
        """Redirect without code parameter raises ValueError."""
        mock_settings.return_value.beatport_client_id = "test-client-id"
        mock_settings.return_value.beatport_redirect_uri = "https://example.com/callback"
        mock_settings.return_value.beatport_auth_base_url = "https://api.beatport.com/v4/auth"

        login_response = MagicMock()
        login_response.json.return_value = {"username": "dj", "email": "dj@test.com"}
        login_response.raise_for_status = MagicMock()

        authorize_response = MagicMock()
        authorize_response.status_code = 302
        authorize_response.headers = {"location": "/callback?error=access_denied"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = login_response
        mock_client.get.return_value = authorize_response
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="No authorization code"):
            login_and_get_tokens("dj", "pass")


class TestDefaultTokenExpiry:
    def test_default_expiry_is_600(self):
        """Default token expiry constant is 600 seconds (10 minutes)."""
        assert DEFAULT_TOKEN_EXPIRY == 600

    def test_save_tokens_uses_600_default(self, db: Session, beatport_user_no_token: User):
        """save_tokens uses 600s default when expires_in is missing."""
        token_data = {"access_token": "tok", "refresh_token": "ref"}
        before = datetime.now(UTC)
        save_tokens(db, beatport_user_no_token, token_data)
        after = datetime.now(UTC)

        db.refresh(beatport_user_no_token)
        expires = beatport_user_no_token.beatport_token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)

        # Should be ~600s from now, not 3600s
        expected_min = before + timedelta(seconds=590)
        expected_max = after + timedelta(seconds=610)
        assert expected_min <= expires <= expected_max


class TestTokenRefreshNoAuthHeader:
    @patch("app.services.beatport.httpx.Client")
    def test_refresh_does_not_send_auth_header(
        self, mock_client_cls, db: Session, beatport_user_expired: User
    ):
        """Token refresh POST does NOT include Authorization header."""
        refresh_response = MagicMock()
        refresh_response.json.return_value = {
            "access_token": "new_token",
            "expires_in": 600,
        }
        refresh_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = refresh_response
        mock_client_cls.return_value = mock_client

        _refresh_token_if_needed(db, beatport_user_expired)

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers")
        assert headers is None


class TestDisconnectRevokesToken:
    @patch("app.services.beatport.httpx.Client")
    def test_disconnect_calls_revoke(self, mock_client_cls, db: Session, beatport_user: User):
        """Disconnect calls Beatport token revocation endpoint."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        disconnect_beatport(db, beatport_user)

        # Verify POST to revocation endpoint was called
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args.args[0].endswith("/o/revoke_token/")

    @patch("app.services.beatport.httpx.Client")
    def test_disconnect_revoke_uses_post_body(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """Disconnect sends revocation params as POST body, not query params."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        disconnect_beatport(db, beatport_user)

        call_kwargs = mock_client.post.call_args
        # Should use data= (POST body), not params= (query string)
        assert "data" in call_kwargs.kwargs
        assert "params" not in call_kwargs.kwargs

    @patch("app.services.beatport.httpx.Client")
    def test_disconnect_succeeds_if_revocation_fails(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """Tokens are cleared even if revocation request fails."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        disconnect_beatport(db, beatport_user)

        db.refresh(beatport_user)
        assert beatport_user.beatport_access_token is None
        assert beatport_user.beatport_refresh_token is None
        assert beatport_user.beatport_token_expires_at is None


class TestRefreshWithoutSecret:
    @patch("app.services.beatport.get_settings")
    @patch("app.services.beatport.httpx.Client")
    def test_refresh_omits_secret_when_empty(
        self, mock_client_cls, mock_settings, db: Session, beatport_user_expired: User
    ):
        """Token refresh excludes client_secret when it's empty."""
        mock_settings.return_value.beatport_client_id = "public-client-id"
        mock_settings.return_value.beatport_client_secret = ""

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "refreshed_token",
            "expires_in": 600,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = _refresh_token_if_needed(db, beatport_user_expired)

        assert result is True
        db.refresh(beatport_user_expired)
        assert beatport_user_expired.beatport_access_token == "refreshed_token"

        call_kwargs = mock_client.post.call_args
        post_data = call_kwargs.kwargs.get("data", {})
        assert "client_secret" not in post_data


class TestLoggerSanitization:
    @patch("app.services.beatport.httpx.Client")
    @patch("app.services.beatport.logger")
    def test_search_error_does_not_log_token(
        self, mock_logger, mock_client_cls, db: Session, beatport_user: User
    ):
        """Search error logs type name, not full exception with tokens."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError(
            "with Bearer sk-secret-token-123 in headers"
        )
        mock_client_cls.return_value = mock_client

        search_beatport_tracks(db, beatport_user, "test query")

        # Verify the logger was called with just the type name, not the full message
        mock_logger.error.assert_called_once()
        log_msg = str(mock_logger.error.call_args)
        assert "Bearer" not in log_msg
        assert "sk-secret" not in log_msg

    @patch("app.services.beatport.httpx.Client")
    @patch("app.services.beatport.logger")
    def test_refresh_error_does_not_log_secret(
        self, mock_logger, mock_client_cls, db: Session, beatport_user_expired: User
    ):
        """Token refresh error logs type name, not credentials."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("client_secret=super-secret-value")
        mock_client_cls.return_value = mock_client

        _refresh_token_if_needed(db, beatport_user_expired)

        mock_logger.error.assert_called_once()
        log_msg = str(mock_logger.error.call_args)
        assert "super-secret" not in log_msg
        assert "client_secret" not in log_msg


@pytest.fixture
def beatport_event(db: Session, beatport_user: User) -> Event:
    """Event with Beatport sync enabled."""
    from datetime import UTC, datetime, timedelta

    event = Event(
        code="BPTEST",
        join_code="CPTEST",
        name="BP Playlist Test",
        created_by_user_id=beatport_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
        beatport_sync_enabled=True,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


class TestBeatportPlaylist:
    @patch("app.services.beatport.httpx.Client")
    def test_create_playlist_success(
        self, mock_client_cls, db: Session, beatport_user: User, beatport_event: Event
    ):
        """Successful playlist creation returns playlist ID and saves to event."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 42}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = create_beatport_playlist(db, beatport_user, beatport_event)

        assert result == "42"
        db.refresh(beatport_event)
        assert beatport_event.beatport_playlist_id == "42"

    def test_create_playlist_returns_existing(
        self, db: Session, beatport_user: User, beatport_event: Event
    ):
        """Event already has beatport_playlist_id — returns it without API call."""
        beatport_event.beatport_playlist_id = "existing-99"
        db.commit()

        result = create_beatport_playlist(db, beatport_user, beatport_event)
        assert result == "existing-99"

    @patch("app.services.beatport.httpx.Client")
    def test_create_playlist_handles_error(
        self, mock_client_cls, db: Session, beatport_user: User, beatport_event: Event
    ):
        """HTTP error during playlist creation returns None."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        result = create_beatport_playlist(db, beatport_user, beatport_event)
        assert result is None

    @patch("app.services.beatport.httpx.Client")
    def test_add_track_sends_singular_int(self, mock_client_cls, db: Session, beatport_user: User):
        """Track ID is sent as singular int via 'track_id' field."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from app.services.beatport import add_track_to_beatport_playlist

        result = add_track_to_beatport_playlist(db, beatport_user, "playlist-1", "12345")

        assert result is True
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json", {})
        assert body == {"track_id": 12345}

    @patch("app.services.beatport.httpx.Client")
    def test_add_tracks_batch_calls_per_track(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """Batch add sends one request per track."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = add_tracks_to_beatport_playlist(
            db, beatport_user, "playlist-1", ["12345", "67890"]
        )

        assert result is True
        assert mock_client.post.call_count == 2

    @patch("app.services.beatport.httpx.Client")
    def test_add_track_handles_error(self, mock_client_cls, db: Session, beatport_user: User):
        """HTTP error during add track returns False."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        from app.services.beatport import add_track_to_beatport_playlist

        result = add_track_to_beatport_playlist(db, beatport_user, "playlist-1", "99999")
        assert result is False


class TestFetchSubscriptionType:
    @patch("app.services.beatport.httpx.Client")
    def test_fetch_subscription_streaming(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns 'streaming' when account has streaming_audio_format_id in preferences."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "username": "dj_test",
            "preferences": {"streaming_audio_format_id": 29},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = fetch_subscription_type(db, beatport_user)

        assert result == "streaming"
        db.refresh(beatport_user)
        assert beatport_user.beatport_subscription == "streaming"

    @patch("app.services.beatport.httpx.Client")
    def test_fetch_subscription_none(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns None when account has no streaming preferences."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"username": "dj_test", "preferences": {}}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = fetch_subscription_type(db, beatport_user)

        assert result is None
        db.refresh(beatport_user)
        assert beatport_user.beatport_subscription is None

    @patch("app.services.beatport.httpx.Client")
    def test_fetch_subscription_handles_error(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """HTTP error returns None without crashing."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        result = fetch_subscription_type(db, beatport_user)
        assert result is None


class TestListUserPlaylists:
    @patch("app.services.beatport.httpx.Client")
    def test_list_playlists_success(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns parsed playlist info from API response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": 42,
                    "name": "My Playlist",
                    "track_count": 10,
                    "description": "Best tracks",
                    "image": {"uri": "https://geo-media.beatport.com/cover.jpg"},
                },
                {
                    "id": 43,
                    "name": "Empty Playlist",
                    "track_count": 0,
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        results = list_user_playlists(db, beatport_user)

        assert len(results) == 2
        assert results[0].id == "42"
        assert results[0].name == "My Playlist"
        assert results[0].num_tracks == 10
        assert results[0].cover_url == "https://geo-media.beatport.com/cover.jpg"
        assert results[0].source == "beatport"
        assert results[1].cover_url is None

    @patch("app.services.beatport.httpx.Client")
    def test_list_playlists_error_returns_empty(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """HTTP error returns empty list."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        results = list_user_playlists(db, beatport_user)
        assert results == []

    def test_list_playlists_no_token(self, db: Session, beatport_user_no_token: User):
        """No token returns empty list."""
        results = list_user_playlists(db, beatport_user_no_token)
        assert results == []


class TestGetPlaylistTracks:
    @patch("app.services.beatport.httpx.Client")
    def test_get_tracks_success(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns parsed tracks from playlist."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "track": {
                        "id": 12345,
                        "name": "Strobe",
                        "slug": "strobe",
                        "mix_name": "Original Mix",
                        "artists": [{"name": "deadmau5"}],
                        "genre": {"name": "Progressive House"},
                        "bpm": 128,
                        "key": {"name": "A min"},
                        "length": "10:33",
                        "image": {"uri": "https://geo-media.beatport.com/art.jpg"},
                    }
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        results = get_playlist_tracks(db, beatport_user, "42")

        assert len(results) == 1
        assert results[0].track_id == "12345"
        assert results[0].title == "Strobe"
        assert results[0].artist == "deadmau5"
        assert results[0].genre == "Progressive House"

    @patch("app.services.beatport.httpx.Client")
    def test_get_tracks_error_returns_empty(
        self, mock_client_cls, db: Session, beatport_user: User
    ):
        """HTTP error returns empty list."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        results = get_playlist_tracks(db, beatport_user, "42")
        assert results == []


class TestGetBeatportTrack:
    @patch("app.services.beatport.httpx.Client")
    def test_get_track_success(self, mock_client_cls, db: Session, beatport_user: User):
        """Returns parsed single track."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 12345,
            "name": "Strobe",
            "slug": "strobe",
            "mix_name": "Original Mix",
            "artists": [{"name": "deadmau5"}],
            "genre": {"name": "Progressive House"},
            "bpm": 128,
            "key": {"name": "A min"},
            "length": "10:33",
            "image": {"uri": "https://geo-media.beatport.com/art.jpg"},
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = get_beatport_track(db, beatport_user, "12345")

        assert result is not None
        assert result.track_id == "12345"
        assert result.title == "Strobe"
        assert result.artist == "deadmau5"
        assert result.genre == "Progressive House"
        assert "beatport.com/track/strobe/12345" in result.beatport_url

    @patch("app.services.beatport.httpx.Client")
    def test_get_track_error_returns_none(self, mock_client_cls, db: Session, beatport_user: User):
        """HTTP error returns None."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        result = get_beatport_track(db, beatport_user, "12345")
        assert result is None

    def test_get_track_no_token(self, db: Session, beatport_user_no_token: User):
        """No token returns None."""
        result = get_beatport_track(db, beatport_user_no_token, "12345")
        assert result is None


class TestManualLinkBeatportTrack:
    def test_link_new_track(self):
        """Links a Beatport track to a request with no existing sync results."""
        import json

        from app.schemas.beatport import BeatportSearchResult

        mock_db = MagicMock()
        request = MagicMock()
        request.sync_results_json = None

        track = BeatportSearchResult(
            track_id="12345",
            title="Strobe",
            artist="deadmau5",
            beatport_url="https://beatport.com/track/strobe/12345",
            duration_seconds=633,
        )

        manual_link_beatport_track(mock_db, request, track)

        result = json.loads(request.sync_results_json)
        assert len(result) == 1
        assert result[0]["service"] == "beatport"
        assert result[0]["status"] == "matched"
        assert result[0]["track_id"] == "12345"
        assert result[0]["confidence"] == 1.0
        mock_db.commit.assert_called_once()

    def test_link_replaces_existing_beatport_entry(self):
        """Replaces existing Beatport entry, preserves other services."""
        import json

        from app.schemas.beatport import BeatportSearchResult

        mock_db = MagicMock()
        request = MagicMock()
        request.sync_results_json = json.dumps(
            [
                {"service": "tidal", "status": "matched", "track_id": "t1"},
                {"service": "beatport", "status": "matched", "track_id": "old"},
            ]
        )

        track = BeatportSearchResult(
            track_id="new123",
            title="New Track",
            artist="New Artist",
            beatport_url="https://beatport.com/track/new/new123",
        )

        manual_link_beatport_track(mock_db, request, track)

        result = json.loads(request.sync_results_json)
        assert len(result) == 2
        services = [r["service"] for r in result]
        assert "tidal" in services
        assert "beatport" in services
        bp_entry = next(r for r in result if r["service"] == "beatport")
        assert bp_entry["track_id"] == "new123"


class TestSearchWithExpiredTokenAutoRefresh:
    @patch("app.services.beatport.httpx.Client")
    def test_search_with_expired_token_refreshes_and_succeeds(
        self, mock_client_cls, db: Session, beatport_user_expired: User
    ):
        """Expired token → refresh → search succeeds in one call."""
        # First client instance: refresh
        refresh_response = MagicMock()
        refresh_response.json.return_value = {
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "expires_in": 600,
        }
        refresh_response.raise_for_status = MagicMock()

        # Second client instance: search
        search_response = MagicMock()
        search_response.json.return_value = MOCK_SEARCH_RESPONSE
        search_response.raise_for_status = MagicMock()

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, *args, **kwargs):
                return refresh_response

            def get(self, *args, **kwargs):
                return search_response

        mock_client_cls.return_value = FakeClient()

        results = search_beatport_tracks(db, beatport_user_expired, "deadmau5")

        assert len(results) == 1
        assert results[0].title == "Strobe"
        # Verify token was refreshed
        db.refresh(beatport_user_expired)
        assert beatport_user_expired.beatport_access_token == "new_token"

    @patch("app.services.beatport.httpx.Client")
    def test_refresh_failure_returns_empty(
        self, mock_client_cls, db: Session, beatport_user_expired: User
    ):
        """Expired token + refresh failure → empty results."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        results = search_beatport_tracks(db, beatport_user_expired, "deadmau5")
        assert results == []
