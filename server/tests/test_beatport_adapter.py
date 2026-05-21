"""Tests for Beatport sync adapter pipeline."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.user import User
from app.schemas.beatport import BeatportSearchResult
from app.services.auth import get_password_hash
from app.services.sync.base import SyncStatus
from app.services.sync.beatport_adapter import BeatportSyncAdapter
from app.services.track_normalizer import NormalizedTrack


@pytest.fixture
def adapter():
    return BeatportSyncAdapter()


@pytest.fixture
def bp_user(db: Session) -> User:
    user = User(
        username="bp_adapter_user",
        password_hash=get_password_hash("testpassword123"),
        beatport_access_token="bp_token",
        beatport_refresh_token="bp_refresh",
        beatport_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def bp_event(db: Session, bp_user: User) -> Event:
    event = Event(
        code="BPADPT",
        join_code="CPADPT",
        name="BP Adapter Test",
        created_by_user_id=bp_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
        beatport_sync_enabled=True,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture
def normalized():
    return NormalizedTrack(
        title="strobe",
        artist="deadmau5",
        raw_title="Strobe",
        raw_artist="deadmau5",
    )


def _make_search_result(
    track_id="12345",
    title="Strobe",
    artist="deadmau5",
    mix_name="Original Mix",
    beatport_url="https://www.beatport.com/track/strobe/12345",
    duration_seconds=633,
):
    return BeatportSearchResult(
        track_id=track_id,
        title=title,
        artist=artist,
        mix_name=mix_name,
        beatport_url=beatport_url,
        duration_seconds=duration_seconds,
    )


class TestServiceName:
    def test_service_name(self, adapter):
        assert adapter.service_name == "beatport"


class TestIsConnected:
    def test_connected(self, adapter, bp_user):
        assert adapter.is_connected(bp_user) is True

    def test_not_connected(self, adapter, db: Session):
        user = User(
            username="bp_no_token",
            password_hash=get_password_hash("test"),
        )
        db.add(user)
        db.commit()
        assert adapter.is_connected(user) is False


class TestSearchWithVersionFilter:
    @patch("app.services.sync.beatport_adapter.beatport_service.search_beatport_tracks")
    def test_rejects_karaoke(self, mock_search, adapter, db, bp_user, normalized):
        """Karaoke versions filtered out."""
        mock_search.return_value = [
            _make_search_result(title="Strobe", mix_name="Karaoke Version"),
        ]
        result = adapter.search_track(db, bp_user, normalized)
        assert result is None

    @patch("app.services.sync.beatport_adapter.beatport_service.search_beatport_tracks")
    def test_accepts_original_mix(self, mock_search, adapter, db, bp_user, normalized):
        """Original Mix is accepted."""
        mock_search.return_value = [_make_search_result()]
        result = adapter.search_track(db, bp_user, normalized)
        assert result is not None
        assert result.track_id == "12345"


class TestSearchWithFuzzyScoring:
    @patch("app.services.sync.beatport_adapter.beatport_service.search_beatport_tracks")
    def test_scores_above_threshold(self, mock_search, adapter, db, bp_user, normalized):
        """Good match scores above threshold."""
        mock_search.return_value = [_make_search_result()]
        result = adapter.search_track(db, bp_user, normalized)
        assert result is not None
        assert result.match_confidence >= 0.5

    @patch("app.services.sync.beatport_adapter.beatport_service.search_beatport_tracks")
    def test_scores_below_threshold(self, mock_search, adapter, db, bp_user, normalized):
        """Completely different track scores below threshold."""
        mock_search.return_value = [
            _make_search_result(title="Completely Different", artist="Unknown Artist"),
        ]
        result = adapter.search_track(db, bp_user, normalized)
        assert result is None


class TestEnsurePlaylist:
    @patch("app.services.sync.beatport_adapter.beatport_service.create_beatport_playlist")
    def test_delegates_to_service(self, mock_create, adapter, db, bp_user, bp_event):
        """ensure_playlist delegates to beatport_service.create_beatport_playlist."""
        mock_create.return_value = "playlist-123"
        result = adapter.ensure_playlist(db, bp_user, bp_event)
        assert result == "playlist-123"
        mock_create.assert_called_once_with(db, bp_user, bp_event)


class TestAddToPlaylist:
    @patch("app.services.sync.beatport_adapter.beatport_service.add_track_to_beatport_playlist")
    def test_delegates_to_service(self, mock_add, adapter, db, bp_user):
        """add_to_playlist delegates to beatport_service."""
        mock_add.return_value = True
        result = adapter.add_to_playlist(db, bp_user, "playlist-123", "track-456")
        assert result is True
        mock_add.assert_called_once_with(db, bp_user, "playlist-123", "track-456")


class TestAddTracksToPlaylist:
    @patch("app.services.sync.beatport_adapter.beatport_service.add_tracks_to_beatport_playlist")
    def test_batch_delegates_to_service(self, mock_batch, adapter, db, bp_user):
        """add_tracks_to_playlist delegates to beatport_service batch."""
        mock_batch.return_value = True
        result = adapter.add_tracks_to_playlist(db, bp_user, "playlist-123", ["1", "2", "3"])
        assert result is True
        mock_batch.assert_called_once_with(db, bp_user, "playlist-123", ["1", "2", "3"])


class TestSyncTrackPipeline:
    """Test the full sync_track pipeline (search -> ensure -> add -> ADDED)."""

    @patch("app.services.sync.beatport_adapter.beatport_service.add_track_to_beatport_playlist")
    @patch("app.services.sync.beatport_adapter.beatport_service.create_beatport_playlist")
    @patch("app.services.sync.beatport_adapter.beatport_service.search_beatport_tracks")
    def test_full_pipeline_returns_added(
        self, mock_search, mock_create, mock_add, adapter, db, bp_user, bp_event, normalized
    ):
        """Full pipeline: search -> ensure playlist -> add -> ADDED."""
        mock_search.return_value = [_make_search_result()]
        mock_create.return_value = "playlist-99"
        mock_add.return_value = True

        result = adapter.sync_track(db, bp_user, bp_event, normalized)

        assert result.status == SyncStatus.ADDED
        assert result.track_match is not None
        assert result.track_match.track_id == "12345"
        assert result.playlist_id == "playlist-99"

    @patch("app.services.sync.beatport_adapter.beatport_service.search_beatport_tracks")
    def test_not_found_when_search_empty(
        self, mock_search, adapter, db, bp_user, bp_event, normalized
    ):
        """Search returns nothing -> NOT_FOUND."""
        mock_search.return_value = []

        result = adapter.sync_track(db, bp_user, bp_event, normalized)
        assert result.status == SyncStatus.NOT_FOUND

    @patch("app.services.sync.beatport_adapter.beatport_service.create_beatport_playlist")
    @patch("app.services.sync.beatport_adapter.beatport_service.search_beatport_tracks")
    def test_error_when_playlist_creation_fails(
        self, mock_search, mock_create, adapter, db, bp_user, bp_event, normalized
    ):
        """Playlist creation failure -> ERROR."""
        mock_search.return_value = [_make_search_result()]
        mock_create.return_value = None

        result = adapter.sync_track(db, bp_user, bp_event, normalized)
        assert result.status == SyncStatus.ERROR
        assert "playlist" in (result.error or "").lower()


class TestSyncTrackErrorSanitized:
    @patch("app.services.sync.beatport_adapter.beatport_service.search_beatport_tracks")
    def test_sync_error_message_is_sanitized(
        self, mock_search, adapter, db, bp_user, bp_event, normalized
    ):
        """Exception during sync produces sanitized error, not raw exception."""
        mock_search.side_effect = httpx.ConnectError(
            "Connection with Bearer sk-secret-token to api.beatport.com failed"
        )
        result = adapter.sync_track(db, bp_user, bp_event, normalized)
        assert result.status == SyncStatus.ERROR
        assert "Bearer" not in result.error
        assert "sk-secret" not in result.error
        assert result.error == "External API connection failed"
