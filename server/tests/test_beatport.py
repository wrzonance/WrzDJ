"""Beatport authentication and catalog tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.providers.beatport import (
    BEATPORT_API_BASE,
    DEFAULT_TOKEN_EXPIRY,
    disconnect_beatport,
    login_and_get_tokens,
    save_tokens,
    search_beatport_tracks,
)
from app.services.providers.beatport_account import (
    _authorize_url,
    _token_url,
    ensure_beatport_token,
)
from app.services.providers.beatport_common import parse_duration
from tests.beatport_test_helpers import (
    MOCK_SEARCH_RESPONSE,
    _fixture_beatport_user,  # noqa: F401
    _fixture_beatport_user_expired,  # noqa: F401
    _fixture_beatport_user_no_token,  # noqa: F401
)


class TestSearchBeatportTracks:
    @patch("app.services.providers.beatport_catalog.httpx.Client")
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

    @patch("app.services.providers.beatport_catalog.httpx.Client")
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

    @patch("app.services.providers.beatport_catalog.httpx.Client")
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
        from app.services.providers.beatport import BEATPORT_TRACK_URL

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
    @patch("app.services.providers.beatport_catalog.httpx.Client")
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
    @patch("app.services.providers.beatport_account.httpx.Client")
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

        result = ensure_beatport_token(db, beatport_user_expired)

        assert result is True
        db.refresh(beatport_user_expired)
        assert beatport_user_expired.beatport_access_token == "new_access_token"
        assert beatport_user_expired.beatport_refresh_token == "new_refresh_token"
        # SQLite returns naive datetimes, so compare without timezone
        expires = beatport_user_expired.beatport_token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        assert expires > datetime.now(UTC)

    @patch("app.services.providers.beatport_account.httpx.Client")
    def test_malformed_refresh_response_keeps_expired_tokens(
        self, mock_client_cls, db: Session, beatport_user_expired: User
    ):
        refresh_response = MagicMock()
        refresh_response.json.return_value = {"access_token": 12}
        refresh_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = refresh_response
        mock_client_cls.return_value = mock_client

        assert ensure_beatport_token(db, beatport_user_expired) is False

        db.refresh(beatport_user_expired)
        assert beatport_user_expired.beatport_access_token == "bp_expired_token"
        assert beatport_user_expired.beatport_refresh_token == "bp_refresh_token_789"


class TestParseDuration:
    def test_minutes_seconds(self):
        assert parse_duration("5:30") == 330

    def test_hours_minutes_seconds(self):
        assert parse_duration("1:05:30") == 3930

    def test_none(self):
        assert parse_duration(None) is None

    def test_invalid(self):
        assert parse_duration("invalid") is None


class TestCorrectApiUrls:
    @patch("app.services.providers.beatport_account.get_settings")
    def test_authorize_url_uses_configured_base(self, mock_settings):
        """Authorize URL uses the configured beatport_auth_base_url."""
        mock_settings.return_value.beatport_auth_base_url = "https://account.beatport.com"
        assert _authorize_url() == "https://account.beatport.com/o/authorize/"

    @patch("app.services.providers.beatport_account.get_settings")
    def test_token_url_uses_configured_base(self, mock_settings):
        """Token URL uses the configured beatport_auth_base_url."""
        mock_settings.return_value.beatport_auth_base_url = "https://account.beatport.com"
        assert _token_url() == "https://account.beatport.com/o/token/"

    @patch("app.services.providers.beatport_account.get_settings")
    def test_v4_auth_base_override(self, mock_settings):
        """Auth URLs can be overridden to v4 path for public client testing."""
        mock_settings.return_value.beatport_auth_base_url = "https://api.beatport.com/v4/auth"
        assert _authorize_url() == "https://api.beatport.com/v4/auth/o/authorize/"
        assert _token_url() == "https://api.beatport.com/v4/auth/o/token/"


class TestLoginAndGetTokens:
    @patch("app.services.providers.beatport_account.get_settings")
    @patch("app.services.providers.beatport_account.httpx.Client")
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
            "token_type": "Bearer",
            "scope": "catalog",
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
        assert result["expires_in"] == 600
        assert result["token_type"] == "Bearer"
        assert result["scope"] == "catalog"

    @pytest.mark.parametrize(
        "token_payload",
        [
            [],
            {"refresh_token": "refresh-without-access"},
            {"access_token": 17},
            {"access_token": "valid-access", "expires_in": "600"},
            {"access_token": "valid-access", "expires_in": True},
            {"access_token": "valid-access", "refresh_token": 17},
            {"access_token": "valid-access", "token_type": None},
            {"access_token": "valid-access", "scope": []},
        ],
    )
    @patch("app.services.providers.beatport_account.get_settings")
    @patch("app.services.providers.beatport_account.httpx.Client")
    def test_login_rejects_malformed_token_response(
        self, mock_client_cls, mock_settings, token_payload
    ):
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
        token_response.json.return_value = token_payload
        token_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [login_response, token_response]
        mock_client.get.return_value = authorize_response
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="Invalid Beatport token response"):
            login_and_get_tokens("dj_test", "password123")

    @patch("app.services.providers.beatport_account.get_settings")
    @patch("app.services.providers.beatport_account.httpx.Client")
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

    @patch("app.services.providers.beatport_account.get_settings")
    @patch("app.services.providers.beatport_account.httpx.Client")
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

    @patch("app.services.providers.beatport_account.get_settings")
    @patch("app.services.providers.beatport_account.httpx.Client")
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

    @patch("app.services.providers.beatport_account.get_settings")
    @patch("app.services.providers.beatport_account.httpx.Client")
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
    @patch("app.services.providers.beatport_account.httpx.Client")
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

        ensure_beatport_token(db, beatport_user_expired)

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers")
        assert headers is None


class TestDisconnectRevokesToken:
    @patch("app.services.providers.beatport_account.httpx.Client")
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

    @patch("app.services.providers.beatport_account.httpx.Client")
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

    @patch("app.services.providers.beatport_account.httpx.Client")
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
    @patch("app.services.providers.beatport_account.get_settings")
    @patch("app.services.providers.beatport_account.httpx.Client")
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

        result = ensure_beatport_token(db, beatport_user_expired)

        assert result is True
        db.refresh(beatport_user_expired)
        assert beatport_user_expired.beatport_access_token == "refreshed_token"

        call_kwargs = mock_client.post.call_args
        post_data = call_kwargs.kwargs.get("data", {})
        assert "client_secret" not in post_data


class TestLoggerSanitization:
    @patch("app.services.providers.beatport_catalog.httpx.Client")
    @patch("app.services.providers.beatport_catalog.logger")
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

    @patch("app.services.providers.beatport_account.httpx.Client")
    @patch("app.services.providers.beatport_account.logger")
    def test_refresh_error_does_not_log_secret(
        self, mock_logger, mock_client_cls, db: Session, beatport_user_expired: User
    ):
        """Token refresh error logs type name, not credentials."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("client_secret=super-secret-value")
        mock_client_cls.return_value = mock_client

        ensure_beatport_token(db, beatport_user_expired)

        mock_logger.error.assert_called_once()
        log_msg = str(mock_logger.error.call_args)
        assert "super-secret" not in log_msg
        assert "client_secret" not in log_msg
