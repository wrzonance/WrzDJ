"""Tidal account, search, and result conversion tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.request import Request, TidalSyncStatus
from app.models.user import User
from app.services.providers.tidal import (
    cancel_device_login,
    check_device_login,
    disconnect_tidal,
    get_tidal_session,
    manual_link_track,
    search_tidal_tracks,
    search_track,
    start_device_login,
)
from app.services.providers.tidal_results import track_to_result as _track_to_result
from tests.tidal_test_helpers import (
    _fixture_tidal_event,  # noqa: F401
    _fixture_tidal_request,  # noqa: F401
    _fixture_tidal_user,  # noqa: F401
    _make_mock_track,
)


class TestTidalDeviceLogin:
    """Tests for Tidal device login flow."""

    @patch("app.services.providers.tidal_account.tidalapi.Session")
    def test_start_device_login(self, mock_session_class: MagicMock, test_user: User):
        """Test starting device login flow."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_login = MagicMock()
        mock_login.verification_uri_complete = "link.tidal.com/ABCDEF"
        mock_login.user_code = "ABCDEF"

        mock_future = MagicMock()
        mock_session.login_oauth.return_value = (mock_login, mock_future)

        result = start_device_login(test_user)

        assert "verification_url" in result
        assert result["verification_url"] == "https://link.tidal.com/ABCDEF"
        assert result["user_code"] == "ABCDEF"

    @patch("app.services.providers.tidal_account.tidalapi.Session")
    def test_start_device_login_with_https(self, mock_session_class: MagicMock, test_user: User):
        """Test device login with URL that already has https."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_login = MagicMock()
        mock_login.verification_uri_complete = "https://link.tidal.com/XYZABC"
        mock_login.user_code = "XYZABC"

        mock_future = MagicMock()
        mock_session.login_oauth.return_value = (mock_login, mock_future)

        result = start_device_login(test_user)

        assert result["verification_url"] == "https://link.tidal.com/XYZABC"

    def test_cancel_device_login(self, test_user: User):
        """Test cancelling device login clears state."""
        # This should not raise even if no pending login
        cancel_device_login(test_user)


class TestTidalStatus:
    """Tests for Tidal account status."""

    def test_status_linked(self, client: TestClient, db: Session, tidal_user: User):
        """Test status shows linked account."""
        # Login as tidal user
        response = client.post(
            "/api/auth/login",
            data={"username": "tidaluser", "password": "testpassword123"},
        )
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get("/api/tidal/status", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["linked"] is True
        assert data["user_id"] == "12345"

    def test_status_not_linked(self, client: TestClient, auth_headers: dict):
        """Test status shows unlinked account."""
        response = client.get("/api/tidal/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["linked"] is False

    def test_status_includes_integration_enabled(self, client: TestClient, auth_headers: dict):
        """Test status includes integration_enabled flag."""
        response = client.get("/api/tidal/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["integration_enabled"] is True

    def test_status_disabled_when_admin_disables(
        self, client: TestClient, auth_headers: dict, admin_headers: dict
    ):
        """Test status shows integration_enabled=false when admin disables Tidal."""
        client.patch(
            "/api/admin/integrations/tidal",
            headers=admin_headers,
            json={"enabled": False},
        )
        response = client.get("/api/tidal/status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["integration_enabled"] is False


class TestTidalDisconnect:
    """Tests for Tidal disconnect."""

    def test_disconnect(self, db: Session, tidal_user: User):
        """Test disconnecting Tidal account."""
        disconnect_tidal(db, tidal_user)

        db.refresh(tidal_user)
        assert tidal_user.tidal_access_token is None
        assert tidal_user.tidal_refresh_token is None
        assert tidal_user.tidal_user_id is None


class TestTidalManualLink:
    """Tests for manual track linking."""

    @patch("app.services.providers.tidal_request_sync.add_track_to_playlist")
    def test_manual_link_success(
        self,
        mock_add: MagicMock,
        db: Session,
        tidal_request: Request,
    ):
        """Test successful manual track link."""
        mock_add.return_value = True

        result = manual_link_track(db, tidal_request, "manual_track_id")

        assert result.status == TidalSyncStatus.SYNCED
        assert result.tidal_track_id == "manual_track_id"

    def test_manual_link_no_tidal_account(
        self,
        db: Session,
        tidal_request: Request,
    ):
        """Test manual link fails without Tidal account."""
        tidal_request.event.created_by.tidal_access_token = None
        db.commit()

        result = manual_link_track(db, tidal_request, "track_id")

        assert result.status == TidalSyncStatus.ERROR
        assert "not linked" in result.error


class TestTidalSearch:
    def test_search_rejects_query_over_200_characters(
        self, client: TestClient, auth_headers: dict[str, str]
    ):
        response = client.get("/api/tidal/search", params={"q": "a" * 201}, headers=auth_headers)

        assert response.status_code == 422

    """Tests for Tidal search functions."""

    @patch("app.services.providers.tidal_search.get_tidal_session")
    def test_search_track_exact_match(self, mock_session_fn: MagicMock, db: Session, tidal_user):
        """Test search_track returns exact match when available."""
        mock_session = MagicMock()
        mock_track = _make_mock_track(
            12345,
            "Strobe",
            "deadmau5",
            "For Lack of a Better Name",
            bpm=128,
            key="A Minor",
            cover_url="https://img.tidal.com/cover.jpg",
        )

        mock_session.search.return_value = {"tracks": [mock_track]}
        mock_session_fn.return_value = mock_session

        result = search_track(db, tidal_user, "deadmau5", "Strobe")

        assert result is not None
        assert result.track_id == "12345"
        assert result.title == "Strobe"
        assert result.artist == "deadmau5"

    @patch("app.services.providers.tidal_search.get_tidal_session")
    def test_search_track_fallback_to_first(self, mock_session_fn: MagicMock, db, tidal_user):
        """Test search_track falls back to first result if no exact match."""
        mock_session = MagicMock()
        mock_track = _make_mock_track(99999, "Some Other Track", "Other Artist", "Album")

        mock_session.search.return_value = {"tracks": [mock_track]}
        mock_session_fn.return_value = mock_session

        result = search_track(db, tidal_user, "deadmau5", "Strobe")

        assert result is not None
        assert result.track_id == "99999"

    @patch("app.services.providers.tidal_search.get_tidal_session")
    def test_search_track_no_results(self, mock_session_fn: MagicMock, db, tidal_user):
        """Test search_track returns None when no results."""
        mock_session = MagicMock()
        mock_session.search.return_value = {"tracks": []}
        mock_session_fn.return_value = mock_session

        result = search_track(db, tidal_user, "deadmau5", "Nonexistent")

        assert result is None

    @patch("app.services.providers.tidal_search.get_tidal_session")
    def test_search_track_no_session(self, mock_session_fn: MagicMock, db, tidal_user):
        """Test search_track returns None when no session."""
        mock_session_fn.return_value = None

        result = search_track(db, tidal_user, "deadmau5", "Strobe")

        assert result is None

    @patch("app.services.providers.tidal_catalog.get_tidal_session")
    def test_search_tidal_tracks(self, mock_session_fn: MagicMock, db, tidal_user):
        """Test search_tidal_tracks returns list of results."""
        mock_session = MagicMock()
        mock_track1 = _make_mock_track(
            111,
            "Track A",
            "Artist A",
            "Album A",
            bpm=125,
            key="C Major",
        )
        mock_track2 = _make_mock_track(222, "Track B", "Artist B", "Album B")

        mock_session.search.return_value = {"tracks": [mock_track1, mock_track2]}
        mock_session_fn.return_value = mock_session

        results = search_tidal_tracks(db, tidal_user, "test", limit=10)

        assert len(results) == 2
        assert results[0].track_id == "111"
        assert results[1].track_id == "222"

    @patch("app.services.providers.tidal_catalog.get_tidal_session")
    def test_search_tidal_tracks_no_session(self, mock_session_fn: MagicMock, db, tidal_user):
        """Test search_tidal_tracks returns empty when no session."""
        mock_session_fn.return_value = None

        results = search_tidal_tracks(db, tidal_user, "test")

        assert results == []


class TestCheckDeviceLogin:
    """Tests for check_device_login."""

    def test_no_pending_login(self, db, tidal_user):
        """Returns error when no pending login for user."""
        result = check_device_login(db, tidal_user)
        assert result["complete"] is False
        assert "No pending" in result.get("error", "")

    @patch("app.services.providers.tidal_account._device_logins", {})
    def test_pending_future_not_done(self, db, tidal_user):
        """Returns pending status when future is not done."""
        from app.services.providers.tidal_account import _device_logins

        mock_state = MagicMock()
        mock_state.created_at = datetime.now(UTC)
        mock_state.future.done.return_value = False
        mock_state.login_info.verification_uri_complete = "https://link.tidal.com/ABCDE"
        mock_state.login_info.user_code = "ABCDE"
        _device_logins[tidal_user.id] = mock_state

        result = check_device_login(db, tidal_user)
        assert result["complete"] is False
        assert result["pending"] is True
        assert result["user_code"] == "ABCDE"

    @patch("app.services.providers.tidal_account._device_logins", {})
    def test_completed_successfully(self, db, tidal_user):
        """Saves tokens and returns complete=True."""
        from app.services.providers.tidal_account import _device_logins

        mock_state = MagicMock()
        mock_state.created_at = datetime.now(UTC)
        mock_state.future.done.return_value = True
        mock_state.future.result.return_value = None
        mock_state.session.access_token = "new_access"
        mock_state.session.refresh_token = "new_refresh"
        mock_state.session.expiry_time = datetime.now(UTC) + timedelta(hours=1)
        mock_state.session.user = MagicMock()
        mock_state.session.user.id = 99999
        _device_logins[tidal_user.id] = mock_state

        result = check_device_login(db, tidal_user)
        assert result["complete"] is True
        assert result["user_id"] == "99999"

    @patch("app.services.providers.tidal_account._device_logins", {})
    def test_completed_with_failure(self, db, tidal_user):
        """Returns error when future raises exception."""
        from app.services.providers.tidal_account import _device_logins

        mock_state = MagicMock()
        mock_state.created_at = datetime.now(UTC)
        mock_state.future.done.return_value = True
        mock_state.future.result.side_effect = Exception("Auth failed")
        _device_logins[tidal_user.id] = mock_state

        result = check_device_login(db, tidal_user)
        assert result["complete"] is False
        assert "error" in result


class TestGetTidalSession:
    """Tests for get_tidal_session."""

    def test_no_access_token(self, db, tidal_user):
        """Returns None when user has no access token."""
        tidal_user.tidal_access_token = None
        db.commit()
        result = get_tidal_session(db, tidal_user)
        assert result is None

    @patch("tidalapi.Session")
    def test_successful_load(self, mock_session_cls, db, tidal_user):
        """Returns session when login is valid."""
        mock_session = MagicMock()
        mock_session.check_login.return_value = True
        mock_session_cls.return_value = mock_session

        result = get_tidal_session(db, tidal_user)
        assert result is not None
        mock_session.load_oauth_session.assert_called_once()

    @patch("app.services.providers.tidal_account.persist_tidal_token_refresh")
    @patch("tidalapi.Session")
    def test_token_refresh_success(self, mock_session_cls, mock_persist_refresh, db, tidal_user):
        """Refreshes expired token and saves new tokens."""
        mock_session = MagicMock()
        mock_session.check_login.return_value = False
        mock_session.token_refresh.return_value = True
        mock_session.access_token = "refreshed_access"
        mock_session.refresh_token = "refreshed_refresh"
        mock_session.expiry_time = datetime.now(UTC) + timedelta(hours=1)
        mock_session_cls.return_value = mock_session

        result = get_tidal_session(db, tidal_user)
        assert result is not None
        assert tidal_user.tidal_access_token == "refreshed_access"
        mock_persist_refresh.assert_called_once_with(
            db,
            tidal_user.id,
            "refreshed_access",
            "refreshed_refresh",
            mock_session.expiry_time,
        )

    @patch("tidalapi.Session")
    def test_token_refresh_failure(self, mock_session_cls, db, tidal_user):
        """Returns None when refresh fails."""
        mock_session = MagicMock()
        mock_session.check_login.return_value = False
        mock_session.token_refresh.return_value = False
        mock_session_cls.return_value = mock_session

        result = get_tidal_session(db, tidal_user)
        assert result is None

    @patch("tidalapi.Session")
    def test_load_exception(self, mock_session_cls, db, tidal_user):
        """Returns None when session load throws."""
        mock_session = MagicMock()
        mock_session.load_oauth_session.side_effect = Exception("Parse error")
        mock_session_cls.return_value = mock_session

        result = get_tidal_session(db, tidal_user)
        assert result is None

    @patch("tidalapi.Session")
    def test_load_exception_does_not_log_exception_message(
        self, mock_session_cls, db, tidal_user, caplog
    ):
        secret = "token=do-not-log"
        mock_session = MagicMock()
        mock_session.load_oauth_session.side_effect = RuntimeError(secret)
        mock_session_cls.return_value = mock_session

        assert get_tidal_session(db, tidal_user) is None
        assert secret not in caplog.text
        assert "RuntimeError" in caplog.text


class TestTidalPlaylistTrackBoundary:
    @patch("app.services.providers.tidal_catalog.track_to_result")
    @patch("app.services.providers.tidal_catalog.get_tidal_session")
    def test_playlist_tracks_are_provider_dtos(
        self, mock_get_session, mock_to_result, db, tidal_user
    ):
        from app.schemas.tidal import TidalSearchResult
        from app.services.providers.tidal import get_playlist_tracks

        raw_track = MagicMock()
        expected = TidalSearchResult(track_id="42", title="Track", artist="Artist")
        session = MagicMock()
        session.playlist.return_value.tracks.return_value = [raw_track]
        mock_get_session.return_value = session
        mock_to_result.return_value = expected

        results = get_playlist_tracks(db, tidal_user, "playlist-id")

        assert results == [expected]
        mock_to_result.assert_called_once_with(raw_track)


class TestTrackToResult:
    """Tests for _track_to_result conversion."""

    def test_full_conversion(self):
        """Converts track with all fields including popularity/isrc/version/explicit."""
        track = _make_mock_track(
            12345,
            "Strobe",
            "deadmau5",
            "For Lack of a Better Name",
            bpm=128.0,
            key="F Minor",
            duration=630,
            cover_url="https://example.com/art.jpg",
            popularity=85,
            isrc="USRC17600001",
            version="Original Mix",
            explicit=False,
        )

        result = _track_to_result(track)
        assert result.track_id == "12345"
        assert result.title == "Strobe"
        assert result.artist == "deadmau5"
        assert result.bpm == 128.0
        assert result.key == "F Minor"
        assert result.cover_url == "https://example.com/art.jpg"
        assert result.popularity == 85
        assert result.isrc == "USRC17600001"
        assert result.version == "Original Mix"
        assert result.explicit is False

    def test_missing_new_fields_defaults(self):
        """Tracks without popularity/isrc/version/explicit get defaults."""
        track = _make_mock_track(99, "Old Track", "Old Artist")

        result = _track_to_result(track)
        assert result.popularity == 0
        assert result.isrc is None
        assert result.version is None
        assert result.explicit is False

    def test_cover_art_failure(self):
        """Returns None cover_url on image exception."""
        track = _make_mock_track(1, "Test", "Artist", "Album")
        track.album.image.side_effect = Exception("Image not found")

        result = _track_to_result(track)
        assert result.cover_url is None

    def test_bpm_edge_cases(self):
        """Handles non-numeric BPM gracefully."""
        track = _make_mock_track(2, "Test", "Artist", bpm="not_a_number")

        result = _track_to_result(track)
        assert result.bpm is None
        assert result.album is None

    def test_multi_artist_track(self):
        """Joins multiple artist names."""
        artist1 = MagicMock()
        artist1.name = "Artist A"
        artist2 = MagicMock()
        artist2.name = "Artist B"
        track = _make_mock_track(
            3,
            "Collab",
            "Artist A",
            bpm=120,
            artists=[artist1, artist2],
        )

        result = _track_to_result(track)
        assert result.artist == "Artist A, Artist B"


class TestCascadeTidalFlow:
    """Cascade tests: end-to-end flows through multiple service functions."""

    @patch("app.services.providers.tidal_catalog.get_tidal_session")
    def test_session_failure_search_returns_empty(self, mock_session_fn, db, tidal_user):
        """get_tidal_session fails → search_tidal_tracks returns empty."""
        mock_session_fn.return_value = None
        results = search_tidal_tracks(db, tidal_user, "strobe")
        assert results == []

    @patch("app.services.providers.tidal_search.get_tidal_session")
    def test_session_failure_search_track_returns_none(self, mock_session_fn, db, tidal_user):
        """get_tidal_session fails → search_track returns None."""
        mock_session_fn.return_value = None
        result = search_track(db, tidal_user, "deadmau5", "Strobe")
        assert result is None
