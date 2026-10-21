"""Now-playing service tests grouped by lifecycle behavior."""

from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.now_playing import NowPlaying
from app.models.request import Request, RequestStatus
from app.services.bridge_integration import sync_now_playing_from_bridge
from app.services.now_playing import (
    clear_manual_now_playing,
    get_now_playing,
    get_play_history,
    set_manual_now_playing,
)
from tests.now_playing.helpers import utcnow


class TestSetManualNowPlaying:
    """Tests for set_manual_now_playing function."""

    def test_creates_now_playing_for_manual(self, db: Session, test_event: Event):
        """Creates NowPlaying with source='manual' and correct track data."""
        request = Request(
            event_id=test_event.id,
            song_title="Manual Track",
            artist="Manual Artist",
            source="spotify",
            artwork_url="https://example.com/art.jpg",
            status=RequestStatus.PLAYING.value,
            dedupe_key="manual_test_key_1234567",
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        set_manual_now_playing(db, test_event.id, request)

        np = get_now_playing(db, test_event.id)
        assert np is not None
        assert np.title == "Manual Track"
        assert np.artist == "Manual Artist"
        assert np.source == "manual"
        assert np.matched_request_id == request.id
        assert np.album_art_url == "https://example.com/art.jpg"
        assert np.manual_hide_now_playing is False

    def test_archives_previous_track(self, db: Session, test_event: Event):
        """Archives existing NowPlaying to play_history before upserting."""
        # Set up existing NowPlaying with a track
        existing = NowPlaying(
            event_id=test_event.id,
            title="Previous Track",
            artist="Previous Artist",
            source="stagelinq",
            started_at=utcnow(),
        )
        db.add(existing)
        db.commit()

        request = Request(
            event_id=test_event.id,
            song_title="New Manual Track",
            artist="New Artist",
            status=RequestStatus.PLAYING.value,
            dedupe_key="manual_archive_key_12345",
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        set_manual_now_playing(db, test_event.id, request)

        # Previous track should be in history
        items, total = get_play_history(db, test_event.id)
        assert total == 1
        assert items[0].title == "Previous Track"
        assert items[0].artist == "Previous Artist"

    def test_preserves_bridge_status(self, db: Session, test_event: Event):
        """Bridge status fields survive manual upsert."""
        existing = NowPlaying(
            event_id=test_event.id,
            title="",
            artist="",
            bridge_connected=True,
            bridge_device_name="SC6000",
            bridge_last_seen=utcnow(),
        )
        db.add(existing)
        db.commit()

        request = Request(
            event_id=test_event.id,
            song_title="Manual Track",
            artist="Manual Artist",
            status=RequestStatus.PLAYING.value,
            dedupe_key="bridge_preserve_key_123",
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        set_manual_now_playing(db, test_event.id, request)

        np = get_now_playing(db, test_event.id)
        assert np.bridge_connected is True
        assert np.bridge_device_name == "SC6000"
        assert np.bridge_last_seen is not None


class TestClearManualNowPlaying:
    """Tests for clear_manual_now_playing function."""

    def test_clears_manual_source(self, db: Session, test_event: Event):
        """Clears NowPlaying when source is 'manual' and request matches."""
        request = Request(
            event_id=test_event.id,
            song_title="Track To Clear",
            artist="Artist",
            status=RequestStatus.PLAYED.value,
            dedupe_key="clear_manual_key_12345",
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        np = NowPlaying(
            event_id=test_event.id,
            title="Track To Clear",
            artist="Artist",
            source="manual",
            matched_request_id=request.id,
            started_at=utcnow(),
        )
        db.add(np)
        db.commit()

        clear_manual_now_playing(db, test_event.id, request.id)

        np_after = get_now_playing(db, test_event.id)
        assert np_after.title == ""
        assert np_after.artist == ""

    def test_does_not_clear_bridge_source(self, db: Session, test_event: Event):
        """Does NOT clear NowPlaying when source is 'stagelinq' (bridge-owned)."""
        request = Request(
            event_id=test_event.id,
            song_title="Bridge Track",
            artist="Bridge Artist",
            status=RequestStatus.PLAYED.value,
            dedupe_key="bridge_source_key_12345",
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        np = NowPlaying(
            event_id=test_event.id,
            title="Bridge Track",
            artist="Bridge Artist",
            source="stagelinq",
            matched_request_id=request.id,
            started_at=utcnow(),
        )
        db.add(np)
        db.commit()

        clear_manual_now_playing(db, test_event.id, request.id)

        np_after = get_now_playing(db, test_event.id)
        # Should NOT be cleared — bridge owns this
        assert np_after.title == "Bridge Track"


class TestBridgeOverridesManual:
    """Tests for bridge auto-detection overriding manually-playing requests."""

    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_bridge_clears_manual_playing(self, mock_spotify, db: Session, test_event: Event):
        """Bridge update transitions ALL PLAYING requests to PLAYED."""
        mock_spotify.return_value = None

        # Create a manually-playing request
        request = Request(
            event_id=test_event.id,
            song_title="Manual Song",
            artist="Manual Artist",
            status=RequestStatus.PLAYING.value,
            dedupe_key="bridge_override_key_123",
        )
        db.add(request)
        db.commit()
        db.refresh(request)

        # Set up NowPlaying as manual
        np = NowPlaying(
            event_id=test_event.id,
            title="Manual Song",
            artist="Manual Artist",
            source="manual",
            matched_request_id=request.id,
            started_at=utcnow(),
        )
        db.add(np)
        db.commit()

        # Bridge reports a new track
        sync_now_playing_from_bridge(db, "TEST01", "Bridge Track", "Bridge Artist")

        # The manual request should be transitioned to PLAYED
        db.refresh(request)
        assert request.status == RequestStatus.PLAYED.value

    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_bridge_clears_all_playing_requests(self, mock_spotify, db: Session, test_event: Event):
        """Bridge update transitions ALL PLAYING requests, not just matched one."""
        mock_spotify.return_value = None

        # Create two playing requests (shouldn't happen normally, but defensive)
        req1 = Request(
            event_id=test_event.id,
            song_title="Playing Song 1",
            artist="Artist 1",
            status=RequestStatus.PLAYING.value,
            dedupe_key="bridge_clear_all_key_1",
        )
        req2 = Request(
            event_id=test_event.id,
            song_title="Playing Song 2",
            artist="Artist 2",
            status=RequestStatus.PLAYING.value,
            dedupe_key="bridge_clear_all_key_2",
        )
        db.add(req1)
        db.add(req2)
        db.commit()

        # Bridge reports a new track
        sync_now_playing_from_bridge(db, "TEST01", "Bridge Track", "Bridge Artist")

        db.refresh(req1)
        db.refresh(req2)
        assert req1.status == RequestStatus.PLAYED.value
        assert req2.status == RequestStatus.PLAYED.value
