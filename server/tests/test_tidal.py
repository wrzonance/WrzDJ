"""Tests for Tidal sync functionality."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus, TidalSyncStatus
from app.models.user import User
from app.schemas.tidal import TidalSearchResult
from app.services.tidal import (
    _track_to_result,
    cancel_device_login,
    check_device_login,
    disconnect_tidal,
    get_tidal_session,
    manual_link_track,
    search_tidal_tracks,
    search_track,
    start_device_login,
    sync_request_to_tidal,
)


def _make_mock_track(
    track_id: int,
    name: str,
    artist_name: str,
    album_name: str | None = None,
    *,
    bpm: float | None = None,
    key: str | None = None,
    duration: int = 200,
    cover_url: str | None = None,
    popularity: int = 0,
    isrc: str | None = None,
    version: str | None = None,
    explicit: bool = False,
    artists: list | None = None,
) -> MagicMock:
    """Create a properly configured mock tidalapi.Track.

    Sets all fields explicitly so MagicMock doesn't auto-create
    attributes that trip isinstance checks or Pydantic validation.
    """
    track = MagicMock()
    track.id = track_id
    track.name = name
    track.duration = duration
    track.bpm = bpm
    track.key = key
    track.popularity = popularity
    track.isrc = isrc
    track.version = version
    track.explicit = explicit
    track.artists = artists or []
    track.artist = MagicMock()
    track.artist.name = artist_name
    if album_name:
        track.album = MagicMock()
        track.album.name = album_name
        track.album.image.return_value = cover_url
    else:
        track.album = None
    return track


@pytest.fixture
def tidal_user(db: Session) -> User:
    """Create a user with linked Tidal account."""
    from app.services.auth import get_password_hash

    user = User(
        username="tidaluser",
        password_hash=get_password_hash("testpassword123"),
        tidal_access_token="test_access_token",
        tidal_refresh_token="test_refresh_token",
        tidal_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        tidal_user_id="12345",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def tidal_event(db: Session, tidal_user: User) -> Event:
    """Create an event with Tidal sync enabled."""
    event = Event(
        code="TIDAL1",
        name="Tidal Test Event",
        created_by_user_id=tidal_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
        tidal_sync_enabled=True,
        tidal_playlist_id="playlist123",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture
def tidal_request(db: Session, tidal_event: Event) -> Request:
    """Create a test request for Tidal sync."""
    request = Request(
        event_id=tidal_event.id,
        song_title="Test Song",
        artist="Test Artist",
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key="tidal_test_dedupe_key",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


class TestTidalDeviceLogin:
    """Tests for Tidal device login flow."""

    @patch("app.services.tidal.tidalapi.Session")
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

    @patch("app.services.tidal.tidalapi.Session")
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

    @patch("app.services.tidal.add_track_to_playlist")
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


class TestTidalEventSettings:
    """Tests for Tidal event settings API."""

    def test_get_event_settings(
        self, client: TestClient, db: Session, tidal_user: User, tidal_event: Event
    ):
        """Test getting event Tidal settings."""
        response = client.post(
            "/api/auth/login",
            data={"username": "tidaluser", "password": "testpassword123"},
        )
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(
            f"/api/tidal/events/{tidal_event.id}/settings",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tidal_sync_enabled"] is True
        assert data["tidal_playlist_id"] == "playlist123"

    def test_update_event_settings(
        self, client: TestClient, db: Session, tidal_user: User, tidal_event: Event
    ):
        """Test updating event Tidal settings."""
        response = client.post(
            "/api/auth/login",
            data={"username": "tidaluser", "password": "testpassword123"},
        )
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = client.put(
            f"/api/tidal/events/{tidal_event.id}/settings",
            json={"tidal_sync_enabled": False},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tidal_sync_enabled"] is False

    def test_enable_sync_without_tidal_account(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        """Test enabling sync fails without Tidal account."""
        response = client.put(
            f"/api/tidal/events/{test_event.id}/settings",
            json={"tidal_sync_enabled": True},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "without linked Tidal account" in response.json()["detail"]


class TestTidalSyncPipeline:
    """Tests for the sync_request_to_tidal pipeline."""

    @patch("app.services.tidal.add_track_to_playlist")
    @patch("app.services.tidal.search_track")
    @patch("app.services.tidal.create_event_playlist")
    def test_happy_path(
        self,
        mock_create_playlist: MagicMock,
        mock_search: MagicMock,
        mock_add: MagicMock,
        db: Session,
        tidal_request: Request,
    ):
        """Test full sync: search → create playlist → add track."""
        mock_create_playlist.return_value = "playlist123"
        mock_search.return_value = TidalSearchResult(
            track_id="track789",
            title="Test Song",
            artist="Test Artist",
            tidal_url="https://tidal.com/browse/track/track789",
        )
        mock_add.return_value = True

        result = sync_request_to_tidal(db, tidal_request)

        assert result.status == TidalSyncStatus.SYNCED
        assert result.tidal_track_id == "track789"

    def test_sync_disabled(self, db: Session, tidal_request: Request):
        """Test sync returns error when sync disabled on event."""
        tidal_request.event.tidal_sync_enabled = False
        db.commit()

        result = sync_request_to_tidal(db, tidal_request)

        assert result.status == TidalSyncStatus.ERROR
        assert "not enabled" in result.error

    def test_no_tidal_account(self, db: Session, tidal_request: Request):
        """Test sync returns error when user has no Tidal account."""
        tidal_request.event.created_by.tidal_access_token = None
        db.commit()

        result = sync_request_to_tidal(db, tidal_request)

        assert result.status == TidalSyncStatus.ERROR
        assert "not linked" in result.error

    @patch("app.services.tidal.create_event_playlist")
    def test_playlist_creation_failure(
        self,
        mock_create_playlist: MagicMock,
        db: Session,
        tidal_request: Request,
    ):
        """Test sync handles playlist creation failure."""
        mock_create_playlist.return_value = None

        result = sync_request_to_tidal(db, tidal_request)

        assert result.status == TidalSyncStatus.ERROR
        assert "playlist" in result.error.lower()

    @patch("app.services.tidal.search_track")
    @patch("app.services.tidal.create_event_playlist")
    def test_track_not_found(
        self,
        mock_create_playlist: MagicMock,
        mock_search: MagicMock,
        db: Session,
        tidal_request: Request,
    ):
        """Test sync handles track not found."""
        mock_create_playlist.return_value = "playlist123"
        mock_search.return_value = None

        result = sync_request_to_tidal(db, tidal_request)

        assert result.status == TidalSyncStatus.NOT_FOUND

    @patch("app.services.tidal.add_track_to_playlist")
    @patch("app.services.tidal.search_track")
    @patch("app.services.tidal.create_event_playlist")
    def test_add_to_playlist_failure(
        self,
        mock_create_playlist: MagicMock,
        mock_search: MagicMock,
        mock_add: MagicMock,
        db: Session,
        tidal_request: Request,
    ):
        """Test sync handles add-to-playlist failure."""
        mock_create_playlist.return_value = "playlist123"
        mock_search.return_value = TidalSearchResult(
            track_id="track789",
            title="Test Song",
            artist="Test Artist",
        )
        mock_add.return_value = False

        result = sync_request_to_tidal(db, tidal_request)

        assert result.status == TidalSyncStatus.ERROR
        assert "add track" in result.error.lower()


class TestTidalSearch:
    """Tests for Tidal search functions."""

    @patch("app.services.tidal.get_tidal_session")
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

    @patch("app.services.tidal.get_tidal_session")
    def test_search_track_fallback_to_first(self, mock_session_fn: MagicMock, db, tidal_user):
        """Test search_track falls back to first result if no exact match."""
        mock_session = MagicMock()
        mock_track = _make_mock_track(99999, "Some Other Track", "Other Artist", "Album")

        mock_session.search.return_value = {"tracks": [mock_track]}
        mock_session_fn.return_value = mock_session

        result = search_track(db, tidal_user, "deadmau5", "Strobe")

        assert result is not None
        assert result.track_id == "99999"

    @patch("app.services.tidal.get_tidal_session")
    def test_search_track_no_results(self, mock_session_fn: MagicMock, db, tidal_user):
        """Test search_track returns None when no results."""
        mock_session = MagicMock()
        mock_session.search.return_value = {"tracks": []}
        mock_session_fn.return_value = mock_session

        result = search_track(db, tidal_user, "deadmau5", "Nonexistent")

        assert result is None

    @patch("app.services.tidal.get_tidal_session")
    def test_search_track_no_session(self, mock_session_fn: MagicMock, db, tidal_user):
        """Test search_track returns None when no session."""
        mock_session_fn.return_value = None

        result = search_track(db, tidal_user, "deadmau5", "Strobe")

        assert result is None

    @patch("app.services.tidal.get_tidal_session")
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

    @patch("app.services.tidal.get_tidal_session")
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

    @patch("app.services.tidal._device_logins", {})
    def test_pending_future_not_done(self, db, tidal_user):
        """Returns pending status when future is not done."""
        from app.services.tidal import _device_logins

        mock_state = MagicMock()
        mock_state.future.done.return_value = False
        mock_state.login_info.verification_uri_complete = "https://link.tidal.com/ABCDE"
        mock_state.login_info.user_code = "ABCDE"
        _device_logins[tidal_user.id] = mock_state

        result = check_device_login(db, tidal_user)
        assert result["complete"] is False
        assert result["pending"] is True
        assert result["user_code"] == "ABCDE"

    @patch("app.services.tidal._device_logins", {})
    def test_completed_successfully(self, db, tidal_user):
        """Saves tokens and returns complete=True."""
        from app.services.tidal import _device_logins

        mock_state = MagicMock()
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

    @patch("app.services.tidal._device_logins", {})
    def test_completed_with_failure(self, db, tidal_user):
        """Returns error when future raises exception."""
        from app.services.tidal import _device_logins

        mock_state = MagicMock()
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

    @patch("tidalapi.Session")
    def test_token_refresh_success(self, mock_session_cls, db, tidal_user):
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

    @patch("app.services.tidal.get_tidal_session")
    def test_session_failure_search_returns_empty(self, mock_session_fn, db, tidal_user):
        """get_tidal_session fails → search_tidal_tracks returns empty."""
        mock_session_fn.return_value = None
        results = search_tidal_tracks(db, tidal_user, "strobe")
        assert results == []

    @patch("app.services.tidal.get_tidal_session")
    def test_session_failure_search_track_returns_none(self, mock_session_fn, db, tidal_user):
        """get_tidal_session fails → search_track returns None."""
        mock_session_fn.return_value = None
        result = search_track(db, tidal_user, "deadmau5", "Strobe")
        assert result is None


class TestCollectionSync:
    """Tests for pre-event collection playlist sync."""

    @patch("app.services.tidal.add_tracks_to_playlist")
    @patch("app.services.tidal.ensure_collection_playlist")
    @patch("app.services.tidal.search_tidal_tracks")
    def test_sync_collection_stores_track_id(
        self,
        mock_search: MagicMock,
        mock_ensure_playlist: MagicMock,
        mock_add: MagicMock,
        db: Session,
        test_event,
        test_user,
    ):
        """Test that sync_collection_requests_batch stores tidal_collection_track_id."""
        from app.models.request import Request as SongRequest
        from app.services.tidal import sync_collection_requests_batch

        # Create a test request with collection flag
        row = SongRequest(
            event_id=test_event.id,
            song_title="Acid Rain",
            artist="Objekt",
            status=RequestStatus.NEW.value,
            dedupe_key="objekt-acid-rain",
            submitted_during_collection=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        # Mock search result
        mock_result = TidalSearchResult(
            track_id="99887766",
            title="Acid Rain",
            artist="Objekt",
            tidal_url="https://tidal.com/browse/track/99887766",
        )

        # Setup mock returns
        mock_search.return_value = [mock_result]
        mock_ensure_playlist.return_value = "playlist-abc"
        mock_add.return_value = True

        # Call the function
        sync_collection_requests_batch(db, test_user, test_event, [row])

        # Refresh and verify
        db.refresh(row)
        assert row.tidal_collection_track_id == "99887766"


class TestCollectionRemove:
    """Tests for removing tracks from collection playlists."""

    @patch("app.services.tidal.get_tidal_session")
    def test_remove_track_from_collection_playlist_success(
        self, mock_session_fn: MagicMock, test_event, test_user
    ):
        """Test successful removal of track from collection playlist."""
        from app.services.tidal import remove_track_from_collection_playlist

        mock_playlist = MagicMock()
        mock_playlist.remove_by_id.return_value = True
        mock_session = MagicMock()
        mock_session.playlist.return_value = mock_playlist
        mock_session_fn.return_value = mock_session

        test_event.tidal_collection_playlist_id = "pl-123"
        db_mock = MagicMock()

        result = remove_track_from_collection_playlist(db_mock, test_user, test_event, "track-456")

        mock_session.playlist.assert_called_once_with("pl-123")
        mock_playlist.remove_by_id.assert_called_once_with("track-456")
        assert result is True

    @patch("app.services.tidal.get_tidal_session")
    def test_remove_track_from_collection_playlist_no_playlist(
        self, mock_session_fn: MagicMock, test_event, test_user
    ):
        """Test removal fails gracefully when no collection playlist exists."""
        from app.services.tidal import remove_track_from_collection_playlist

        mock_session = MagicMock()
        mock_session_fn.return_value = mock_session
        test_event.tidal_collection_playlist_id = None
        db_mock = MagicMock()

        result = remove_track_from_collection_playlist(db_mock, test_user, test_event, "track-456")

        mock_session.playlist.assert_not_called()
        assert result is False

    @patch("app.services.tidal.remove_track_from_collection_playlist")
    def test_remove_collection_tracks_batch_calls_per_track(
        self, mock_remove: MagicMock, test_event, test_user
    ):
        """Test batch removal calls remove function for each track."""
        from app.services.tidal import remove_collection_tracks_batch

        mock_remove.return_value = True
        test_event.tidal_collection_playlist_id = "pl-123"
        db_mock = MagicMock()

        remove_collection_tracks_batch(db_mock, test_user, test_event, ["t1", "t2", "t3"])

        assert mock_remove.call_count == 3

    @patch("app.services.tidal.get_playlist_tracks")
    def test_poll_tidal_collection_removals_rejects_missing_track(
        self, mock_get_tracks: MagicMock, db: Session, test_event: Event, test_user: User
    ):
        """Test poll detects tracks removed from Tidal playlist and rejects them."""
        from app.services.tidal import poll_tidal_collection_removals

        test_event.tidal_collection_playlist_id = "pl-xyz"
        test_event.created_by = test_user

        kept = Request(
            event_id=test_event.id,
            song_title="Track A",
            artist="Artist A",
            status=RequestStatus.NEW.value,
            dedupe_key="track-a",
            submitted_during_collection=True,
            tidal_collection_track_id="111",
        )
        removed = Request(
            event_id=test_event.id,
            song_title="Track B",
            artist="Artist B",
            status=RequestStatus.NEW.value,
            dedupe_key="track-b",
            submitted_during_collection=True,
            tidal_collection_track_id="222",
        )
        db.add_all([kept, removed])
        db.commit()

        mock_track = MagicMock()
        mock_track.id = 111  # only "111" still in playlist; "222" was removed

        mock_get_tracks.return_value = [mock_track]

        count = poll_tidal_collection_removals(db, test_event)

        db.refresh(kept)
        db.refresh(removed)

        assert count == 1
        assert kept.status == RequestStatus.NEW.value
        assert removed.status == RequestStatus.REJECTED.value

    @patch("app.services.tidal.get_playlist_tracks")
    def test_poll_tidal_collection_removals_no_playlist_returns_zero(
        self, mock_get_tracks: MagicMock, db: Session, test_event: Event, test_user: User
    ):
        """Test poll returns 0 when event has no collection playlist."""
        from app.services.tidal import poll_tidal_collection_removals

        test_event.tidal_collection_playlist_id = None
        test_event.created_by = test_user

        count = poll_tidal_collection_removals(db, test_event)

        mock_get_tracks.assert_not_called()
        assert count == 0

    @patch("app.services.tidal.get_playlist_tracks")
    def test_poll_tidal_collection_removals_skips_already_rejected(
        self, mock_get_tracks: MagicMock, db: Session, test_event: Event, test_user: User
    ):
        """Test poll does not double-count already rejected requests."""
        from app.services.tidal import poll_tidal_collection_removals

        test_event.tidal_collection_playlist_id = "pl-xyz"
        test_event.created_by = test_user

        already_rejected = Request(
            event_id=test_event.id,
            song_title="Old Track",
            artist="Artist",
            status=RequestStatus.REJECTED.value,
            dedupe_key="old-track",
            submitted_during_collection=True,
            tidal_collection_track_id="333",
        )
        db.add(already_rejected)
        db.commit()

        mock_get_tracks.return_value = []

        count = poll_tidal_collection_removals(db, test_event)

        assert count == 0  # already rejected — not double-counted
