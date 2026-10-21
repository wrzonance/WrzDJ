"""Tidal synchronization and collection tests."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus, TidalSyncStatus
from app.models.user import User
from app.schemas.tidal import TidalSearchResult
from app.services.providers.tidal import (
    create_event_playlist,
    ensure_collection_playlist,
    sync_request_to_tidal,
)
from app.services.sync.base import SyncStatus
from tests.tidal_test_helpers import (
    _fixture_tidal_event,  # noqa: F401
    _fixture_tidal_request,  # noqa: F401
    _fixture_tidal_user,  # noqa: F401
    _make_mock_track,
)


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

    @patch("app.services.providers.tidal_request_sync.add_track_to_playlist")
    @patch("app.services.providers.tidal_request_sync.search_track")
    @patch("app.services.providers.tidal_request_sync.create_event_playlist")
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

    @patch("app.services.providers.tidal_request_sync.create_event_playlist")
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

    @patch("app.services.providers.tidal_request_sync.search_track")
    @patch("app.services.providers.tidal_request_sync.create_event_playlist")
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

    @patch("app.services.providers.tidal_request_sync.add_track_to_playlist")
    @patch("app.services.providers.tidal_request_sync.search_track")
    @patch("app.services.providers.tidal_request_sync.create_event_playlist")
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

    @patch("app.services.providers.tidal_request_sync.add_track_to_playlist")
    @patch("app.services.providers.tidal_request_sync.search_track")
    @patch("app.services.providers.tidal_request_sync.create_event_playlist")
    def test_successful_sync_updates_sync_results_json_to_added(
        self,
        mock_create_playlist: MagicMock,
        mock_search: MagicMock,
        mock_add: MagicMock,
        db: Session,
        tidal_request: Request,
    ):
        """A successful manual sync must replace a stale error entry with 'added'.

        The dashboard badge renders from sync_results_json; without this the chip
        stays red after a retry that actually succeeded (feedback loop missing on
        the manual path).
        """
        import json

        tidal_request.sync_results_json = json.dumps(
            [{"service": "tidal", "status": "error", "error": "old failure"}]
        )
        db.commit()

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
        entries = json.loads(tidal_request.sync_results_json)
        tidal_entries = [e for e in entries if e["service"] == "tidal"]
        assert len(tidal_entries) == 1  # upsert, not appended twice
        assert tidal_entries[0]["status"] == "added"
        assert tidal_entries[0]["url"] == "https://tidal.com/browse/track/track789"

    @patch("app.services.providers.tidal_request_sync.search_track")
    @patch("app.services.providers.tidal_request_sync.create_event_playlist")
    def test_not_found_sync_updates_sync_results_json(
        self,
        mock_create_playlist: MagicMock,
        mock_search: MagicMock,
        db: Session,
        tidal_request: Request,
    ):
        """A not-found manual sync records 'not_found' so the badge shows T?."""
        import json

        mock_create_playlist.return_value = "playlist123"
        mock_search.return_value = None

        result = sync_request_to_tidal(db, tidal_request)

        assert result.status == TidalSyncStatus.NOT_FOUND
        entries = json.loads(tidal_request.sync_results_json)
        tidal_entry = next(e for e in entries if e["service"] == "tidal")
        assert tidal_entry["status"] == "not_found"

    def test_record_tidal_sync_result_tolerates_non_dict_entries(self):
        """Upsert must not crash on corrupt/legacy sync_results_json with non-dict items."""
        import json

        from app.services.providers.tidal_request_sync import _record_tidal_sync_result

        request = MagicMock()
        request.sync_results_json = json.dumps(
            ["corrupt-string", {"service": "tidal", "status": "error"}, {"service": "beatport"}]
        )

        _record_tidal_sync_result(request, SyncStatus.ADDED, url="u", track_id="t")

        entries = json.loads(request.sync_results_json)
        tidal = [e for e in entries if isinstance(e, dict) and e.get("service") == "tidal"]
        assert len(tidal) == 1
        assert tidal[0]["status"] == "added"
        # other services' entries are preserved
        assert any(isinstance(e, dict) and e.get("service") == "beatport" for e in entries)


class TestPlaylistSelfHeal:
    """A stored Tidal playlist deleted out-of-band must self-heal, not fail forever.

    Regression for production event ELZ2G2: the accepted playlist was deleted on
    Tidal, so create_event_playlist kept returning a dead ID and every accept-sync
    404'd (red "T!"). The fix validates the stored playlist and recreates it when
    Tidal reports it gone (ObjectNotFound), while leaving it untouched on a
    transient API error so a real playlist is never destroyed on a blip.
    """

    @patch("app.services.providers.tidal_playlists.get_tidal_session")
    def test_create_event_playlist_recreates_when_deleted(
        self, mock_session_fn: MagicMock, db: Session, tidal_event: Event
    ):
        """A 404 (ObjectNotFound) on the stored playlist clears it and creates a fresh one."""
        from tidalapi.exceptions import ObjectNotFound

        mock_session = MagicMock()
        mock_session.playlist.side_effect = ObjectNotFound("Playlist with id playlist123 not found")
        new_playlist = MagicMock()
        new_playlist.id = "fresh456"
        mock_session.user.create_playlist.return_value = new_playlist
        mock_session_fn.return_value = mock_session

        result = create_event_playlist(db, tidal_event.created_by, tidal_event)

        assert result == "fresh456"
        assert tidal_event.tidal_playlist_id == "fresh456"
        mock_session.user.create_playlist.assert_called_once()

    @patch("app.services.providers.tidal_playlists.get_tidal_session")
    def test_create_event_playlist_keeps_valid_playlist(
        self, mock_session_fn: MagicMock, db: Session, tidal_event: Event
    ):
        """A stored playlist that still exists is returned without recreating."""
        mock_session = MagicMock()
        mock_session.playlist.return_value = MagicMock()  # resolves → playlist exists
        mock_session_fn.return_value = mock_session

        result = create_event_playlist(db, tidal_event.created_by, tidal_event)

        assert result == "playlist123"
        mock_session.user.create_playlist.assert_not_called()

    @patch("app.services.providers.tidal_playlists.get_tidal_session")
    def test_create_event_playlist_keeps_id_on_transient_error(
        self, mock_session_fn: MagicMock, db: Session, tidal_event: Event
    ):
        """A transient (non-404) verify error must NOT destroy/recreate a real playlist."""
        mock_session = MagicMock()
        mock_session.playlist.side_effect = ConnectionError("network blip")
        mock_session_fn.return_value = mock_session

        result = create_event_playlist(db, tidal_event.created_by, tidal_event)

        assert result == "playlist123"
        assert tidal_event.tidal_playlist_id == "playlist123"
        mock_session.user.create_playlist.assert_not_called()

    @patch("app.services.providers.tidal_playlists.get_tidal_session")
    def test_ensure_collection_playlist_recreates_when_deleted(
        self, mock_session_fn: MagicMock, db: Session, tidal_event: Event
    ):
        """The separate collection playlist self-heals on the same ObjectNotFound class."""
        from tidalapi.exceptions import ObjectNotFound

        tidal_event.tidal_collection_playlist_id = "collection-dead"
        db.commit()

        mock_session = MagicMock()
        mock_session.playlist.side_effect = ObjectNotFound("Playlist not found")
        new_playlist = MagicMock()
        new_playlist.id = "collection-fresh"
        mock_session.user.create_playlist.return_value = new_playlist
        mock_session_fn.return_value = mock_session

        result = ensure_collection_playlist(db, tidal_event.created_by, tidal_event)

        assert result == "collection-fresh"
        assert tidal_event.tidal_collection_playlist_id == "collection-fresh"

    @patch("app.services.providers.tidal_playlists.get_tidal_session")
    def test_sync_request_to_tidal_self_heals_deleted_playlist(
        self, mock_session_fn: MagicMock, db: Session, tidal_request: Request, monkeypatch
    ):
        """End-to-end: accept-sync against a deleted playlist recreates it and succeeds."""
        from tidalapi.exceptions import ObjectNotFound

        dead_id = tidal_request.event.tidal_playlist_id  # "playlist123"
        added_to: list[str] = []

        def playlist_side_effect(pid):
            if pid == dead_id:
                raise ObjectNotFound(f"Playlist with id {pid} not found")
            live = MagicMock()
            live.add.side_effect = lambda ids: added_to.extend(ids)
            return live

        mock_session = MagicMock()
        mock_session.playlist.side_effect = playlist_side_effect
        new_playlist = MagicMock()
        new_playlist.id = "recreated789"
        mock_session.user.create_playlist.return_value = new_playlist
        mock_session.search.return_value = {
            "tracks": [_make_mock_track(555, "Test Song", "Test Artist")]
        }
        mock_session_fn.return_value = mock_session
        monkeypatch.setattr(
            "app.services.providers.tidal_search.get_tidal_session", lambda *_args: mock_session
        )

        result = sync_request_to_tidal(db, tidal_request)

        assert result.status == TidalSyncStatus.SYNCED
        assert tidal_request.event.tidal_playlist_id == "recreated789"
        assert added_to == ["555"]


class TestCollectionSync:
    """Tests for pre-event collection playlist sync."""

    @patch("app.services.providers.tidal_request_sync.add_tracks_to_playlist")
    @patch("app.services.providers.tidal_request_sync.ensure_collection_playlist")
    @patch("app.services.providers.tidal_request_sync.search_tidal_tracks")
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
        from app.services.providers.tidal import sync_collection_requests_batch

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

    @patch("app.services.providers.tidal_playlists.get_tidal_session")
    def test_remove_track_from_collection_playlist_success(
        self, mock_session_fn: MagicMock, test_event, test_user
    ):
        """Test successful removal of track from collection playlist."""
        from app.services.providers.tidal import remove_track_from_collection_playlist

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

    @patch("app.services.providers.tidal_playlists.get_tidal_session")
    def test_remove_track_from_collection_playlist_no_playlist(
        self, mock_session_fn: MagicMock, test_event, test_user
    ):
        """Test removal fails gracefully when no collection playlist exists."""
        from app.services.providers.tidal import remove_track_from_collection_playlist

        mock_session = MagicMock()
        mock_session_fn.return_value = mock_session
        test_event.tidal_collection_playlist_id = None
        db_mock = MagicMock()

        result = remove_track_from_collection_playlist(db_mock, test_user, test_event, "track-456")

        mock_session.playlist.assert_not_called()
        assert result is False

    @patch("app.services.providers.tidal_playlists.remove_track_from_collection_playlist")
    def test_remove_collection_tracks_batch_calls_per_track(
        self, mock_remove: MagicMock, test_event, test_user
    ):
        """Test batch removal calls remove function for each track."""
        from app.services.providers.tidal import remove_collection_tracks_batch

        mock_remove.return_value = True
        test_event.tidal_collection_playlist_id = "pl-123"
        db_mock = MagicMock()

        remove_collection_tracks_batch(db_mock, test_user, test_event, ["t1", "t2", "t3"])

        assert mock_remove.call_count == 3

    @patch("app.services.providers.tidal_playlists.get_playlist_tracks")
    def test_poll_tidal_collection_removals_rejects_missing_track(
        self, mock_get_tracks: MagicMock, db: Session, test_event: Event, test_user: User
    ):
        """Test poll detects tracks removed from Tidal playlist and rejects them."""
        from app.services.providers.tidal import poll_tidal_collection_removals

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

        from app.schemas.tidal import TidalSearchResult

        mock_get_tracks.return_value = [
            TidalSearchResult(track_id="111", title="Track A", artist="Artist A")
        ]

        count = poll_tidal_collection_removals(db, test_event)

        db.refresh(kept)
        db.refresh(removed)

        assert count == 1
        assert kept.status == RequestStatus.NEW.value
        assert removed.status == RequestStatus.REJECTED.value

    @patch("app.services.providers.tidal_playlists.get_playlist_tracks")
    def test_poll_tidal_collection_removals_no_playlist_returns_zero(
        self, mock_get_tracks: MagicMock, db: Session, test_event: Event, test_user: User
    ):
        """Test poll returns 0 when event has no collection playlist."""
        from app.services.providers.tidal import poll_tidal_collection_removals

        test_event.tidal_collection_playlist_id = None
        test_event.created_by = test_user

        count = poll_tidal_collection_removals(db, test_event)

        mock_get_tracks.assert_not_called()
        assert count == 0

    @patch("app.services.providers.tidal_playlists.get_playlist_tracks")
    def test_poll_tidal_collection_removals_skips_already_rejected(
        self, mock_get_tracks: MagicMock, db: Session, test_event: Event, test_user: User
    ):
        """Test poll does not double-count already rejected requests."""
        from app.services.providers.tidal import poll_tidal_collection_removals

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
