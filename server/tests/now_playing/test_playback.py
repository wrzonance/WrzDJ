"""Now-playing service tests grouped by lifecycle behavior."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.now_playing import NowPlaying
from app.models.play_history import PlayHistory
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.bridge_integration import sync_now_playing_from_bridge
from app.services.now_playing import (
    archive_to_history,
    get_next_play_order,
    get_play_history,
    lookup_tidal_album_art,
)
from tests.now_playing.helpers import utcnow


class TestGetNextPlayOrder:
    """Tests for get_next_play_order function."""

    def test_first_entry(self, db: Session, test_event: Event):
        """First play_order is 1."""
        order = get_next_play_order(db, test_event.id)
        assert order == 1

    def test_increments(self, db: Session, test_event: Event):
        """Increments from existing entries."""
        # Add some history
        for i in range(3):
            history = PlayHistory(
                event_id=test_event.id,
                title=f"Track {i}",
                artist="Artist",
                started_at=utcnow(),
                play_order=i + 1,
            )
            db.add(history)
        db.commit()

        order = get_next_play_order(db, test_event.id)
        assert order == 4


class TestArchiveToHistory:
    """Tests for archive_to_history function."""

    def test_creates_history_entry(self, db: Session, test_event: Event):
        """Creates a history entry from now_playing."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            album="Test Album",
            deck="1",
            spotify_track_id="sp123",
            album_art_url="https://example.com/art.jpg",
            spotify_uri="spotify:track:sp123",
            source="stagelinq",
            started_at=utcnow() - timedelta(minutes=5),
        )
        db.add(now_playing)
        db.commit()

        history = archive_to_history(db, now_playing)
        db.commit()

        assert history.event_id == test_event.id
        assert history.title == "Test Track"
        assert history.artist == "Test Artist"
        assert history.album == "Test Album"
        assert history.deck == "1"
        assert history.spotify_track_id == "sp123"
        assert history.source == "stagelinq"
        assert history.play_order == 1
        assert history.ended_at is not None

    def test_preserves_matched_request_id(
        self, db: Session, test_event: Event, accepted_request: Request
    ):
        """Preserves matched_request_id in history."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            source="stagelinq",
            matched_request_id=accepted_request.id,
            started_at=utcnow(),
        )
        db.add(now_playing)
        db.commit()

        history = archive_to_history(db, now_playing)
        db.commit()

        assert history.matched_request_id == accepted_request.id


class TestHandleNowPlayingUpdate:
    """Tests for sync_now_playing_from_bridge function."""

    @patch("app.services.bridge_integration.lookup_spotify_album_art")
    def test_creates_now_playing(self, mock_spotify, db: Session, test_event: Event):
        """Creates a new now_playing record."""
        mock_spotify.return_value = None

        result = sync_now_playing_from_bridge(
            db, "TEST01", "New Track", "New Artist", "Test Album", "1"
        )

        assert result is not None
        assert result.title == "New Track"
        assert result.artist == "New Artist"
        assert result.album == "Test Album"
        assert result.deck == "1"
        assert result.source == "bridge"

    @patch("app.services.bridge_integration.lookup_spotify_album_art")
    def test_archives_previous_track(self, mock_spotify, db: Session, test_event: Event):
        """Archives previous track when new track arrives."""
        mock_spotify.return_value = None

        # First track
        sync_now_playing_from_bridge(db, "TEST01", "First Track", "First Artist")

        # Second track should archive the first
        sync_now_playing_from_bridge(db, "TEST01", "Second Track", "Second Artist")

        # Check history
        items, total = get_play_history(db, test_event.id)
        assert total == 1
        assert items[0].title == "First Track"
        assert items[0].ended_at is not None

    @patch("app.services.bridge_integration.lookup_spotify_album_art")
    def test_auto_matches_request(
        self, mock_spotify, db: Session, test_event: Event, accepted_request: Request
    ):
        """Auto-matches accepted requests."""
        mock_spotify.return_value = None

        result = sync_now_playing_from_bridge(db, "TEST01", "Blue Monday", "New Order")

        # Check request was matched
        db.refresh(accepted_request)
        assert accepted_request.status == RequestStatus.PLAYING.value
        assert result.matched_request_id == accepted_request.id

    @patch("app.services.bridge_integration.lookup_spotify_album_art")
    def test_transitions_request_to_played(
        self, mock_spotify, db: Session, test_event: Event, accepted_request: Request
    ):
        """Transitions matched request to played when next track arrives."""
        mock_spotify.return_value = None

        # First track matches request
        sync_now_playing_from_bridge(db, "TEST01", "Blue Monday", "New Order")

        # Second track should transition request to played
        sync_now_playing_from_bridge(db, "TEST01", "Sandstorm", "Darude")

        db.refresh(accepted_request)
        assert accepted_request.status == RequestStatus.PLAYED.value

    @patch("app.services.bridge_integration.lookup_tidal_album_art")
    @patch("app.services.bridge_integration.lookup_spotify_album_art")
    def test_falls_back_to_spotify_when_tidal_misses(
        self, mock_spotify, mock_tidal, db: Session, test_event: Event
    ):
        """Spotify is the last-resort art source when Tidal returns nothing."""
        mock_tidal.return_value = None
        mock_spotify.return_value = {
            "spotify_track_id": "sp123",
            "album_art_url": "https://example.com/art.jpg",
            "spotify_uri": "spotify:track:sp123",
        }

        result = sync_now_playing_from_bridge(db, "TEST01", "Test Track", "Test Artist")

        assert result.spotify_track_id == "sp123"
        assert result.album_art_url == "https://example.com/art.jpg"
        assert result.spotify_uri == "spotify:track:sp123"

    @patch("app.services.bridge_integration.lookup_tidal_album_art")
    @patch("app.services.bridge_integration.lookup_spotify_album_art")
    def test_prefers_tidal_art_when_no_request_match(
        self, mock_spotify, mock_tidal, db: Session, test_event: Event
    ):
        """With no matching request, art resolves via Tidal (primary) — Spotify untouched."""
        mock_tidal.return_value = "https://tidal.example/cover.jpg"

        result = sync_now_playing_from_bridge(db, "TEST01", "Get Low", "Lil Jon")

        assert result.album_art_url == "https://tidal.example/cover.jpg"
        mock_spotify.assert_not_called()

    @patch("app.services.bridge_integration.lookup_tidal_album_art")
    @patch("app.services.bridge_integration.lookup_spotify_album_art")
    def test_reuses_matched_request_art(
        self, mock_spotify, mock_tidal, db: Session, test_event: Event, accepted_request: Request
    ):
        """A matched request's already-resolved art is reused — no external lookup at all."""
        accepted_request.artwork_url = "https://requests.example/art.jpg"
        db.commit()

        result = sync_now_playing_from_bridge(db, "TEST01", "Blue Monday", "New Order")

        assert result.album_art_url == "https://requests.example/art.jpg"
        assert result.matched_request_id == accepted_request.id
        mock_tidal.assert_not_called()
        mock_spotify.assert_not_called()

    @patch("app.services.bridge_integration.lookup_tidal_album_art")
    @patch("app.services.bridge_integration.lookup_spotify_album_art")
    def test_no_art_when_all_sources_miss(
        self, mock_spotify, mock_tidal, db: Session, test_event: Event
    ):
        """Gracefully leaves art null when request, Tidal, and Spotify all miss."""
        mock_tidal.return_value = None
        mock_spotify.return_value = None

        result = sync_now_playing_from_bridge(db, "TEST01", "Obscure", "Nobody")

        assert result.album_art_url is None

    @patch("app.services.bridge_integration.lookup_spotify_album_art", return_value=None)
    @patch("app.services.bridge_integration.lookup_tidal_album_art")
    def test_art_lookup_runs_before_staging_request_mutation(
        self,
        mock_tidal,
        mock_spotify,
        db: Session,
        test_event: Event,
        accepted_request: Request,
    ):
        """External art lookup runs before the request->PLAYING mutation is staged.
        At lookup time the matched request must still be ACCEPTED (not yet PLAYING).
        """
        seen: dict[str, str] = {}

        def capture(_db, _owner, _title, _artist):
            req = db.query(Request).filter(Request.id == accepted_request.id).first()
            seen["status_at_lookup"] = req.status
            return None

        mock_tidal.side_effect = capture

        sync_now_playing_from_bridge(db, "TEST01", "Blue Monday", "New Order")

        assert seen["status_at_lookup"] == RequestStatus.ACCEPTED.value

    def test_event_not_found(self, db: Session):
        """Returns None for non-existent event."""
        result = sync_now_playing_from_bridge(db, "INVALID", "Test", "Test")
        assert result is None


class TestLookupTidalAlbumArt:
    """Tests for lookup_tidal_album_art (now-playing art via the owner's Tidal session)."""

    @patch("app.services.providers.tidal_search.search_track")
    def test_returns_cover_url_from_tidal(self, mock_search, db: Session, test_user: User):
        """Returns the Tidal cover URL when a track is found."""
        mock_search.return_value = SimpleNamespace(cover_url="https://tidal.example/c.jpg")
        assert lookup_tidal_album_art(db, test_user, "Sandstorm", "Darude") == (
            "https://tidal.example/c.jpg"
        )

    @patch("app.services.providers.tidal_search.search_track")
    def test_returns_none_when_no_track(self, mock_search, db: Session, test_user: User):
        """Returns None when Tidal finds nothing (no session / no match)."""
        mock_search.return_value = None
        assert lookup_tidal_album_art(db, test_user, "Obscure", "Nobody") is None

    @patch("app.services.providers.tidal_search.search_track")
    def test_returns_none_on_error(self, mock_search, db: Session, test_user: User):
        """Swallows Tidal errors — now-playing art is non-critical."""
        mock_search.side_effect = RuntimeError("tidal down")
        assert lookup_tidal_album_art(db, test_user, "Sandstorm", "Darude") is None
