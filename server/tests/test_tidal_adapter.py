"""Tests for Tidal sync adapter."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.user import User
from app.schemas.tidal import TidalSearchResult
from app.services.intent_parser import IntentContext
from app.services.sync.base import SyncStatus
from app.services.sync.tidal_adapter import TidalSyncAdapter
from app.services.track_normalizer import normalize_track


@pytest.fixture
def adapter():
    return TidalSyncAdapter()


@pytest.fixture
def tidal_user(db: Session) -> User:
    from app.services.auth import get_password_hash

    user = User(
        username="tidal_adapter_user",
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
    event = Event(
        code="ADAPT1",
        join_code="ADAPT1J",
        name="Adapter Test Event",
        created_by_user_id=tidal_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
        tidal_sync_enabled=True,
        tidal_playlist_id="playlist_adapt",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


class TestTidalAdapterProperties:
    def test_service_name(self, adapter):
        assert adapter.service_name == "tidal"

    def test_is_connected_true(self, adapter, tidal_user):
        assert adapter.is_connected(tidal_user) is True

    def test_is_connected_false(self, adapter, tidal_user, db):
        tidal_user.tidal_access_token = None
        db.commit()
        assert adapter.is_connected(tidal_user) is False

    def test_is_sync_enabled_true(self, adapter, tidal_event):
        assert adapter.is_sync_enabled(tidal_event) is True

    def test_is_sync_enabled_false(self, adapter, tidal_event, db):
        tidal_event.tidal_sync_enabled = False
        db.commit()
        assert adapter.is_sync_enabled(tidal_event) is False


class TestTidalAdapterSearch:
    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_search_exact_match(self, mock_tidal, adapter, db, tidal_user):
        mock_tidal.search_tidal_tracks.return_value = [
            TidalSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                tidal_url="https://tidal.com/browse/track/123",
                duration_seconds=600,
            ),
        ]

        normalized = normalize_track("Strobe", "deadmau5")
        result = adapter.search_track(db, tidal_user, normalized)

        assert result is not None
        assert result.track_id == "123"
        assert result.service == "tidal"
        assert result.match_confidence > 0.8

    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_search_filters_sped_up(self, mock_tidal, adapter, db, tidal_user):
        """Version filter rejects sped-up when user didn't ask for it."""
        mock_tidal.search_tidal_tracks.return_value = [
            TidalSearchResult(
                track_id="999",
                title="Strobe (Sped Up)",
                artist="deadmau5",
            ),
            TidalSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
            ),
        ]

        normalized = normalize_track("Strobe", "deadmau5")
        result = adapter.search_track(db, tidal_user, normalized)

        assert result is not None
        assert result.track_id == "123"  # Skipped the sped-up version

    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_search_allows_sped_up_with_intent(self, mock_tidal, adapter, db, tidal_user):
        """Version filter allows sped-up when user explicitly asked for it."""
        mock_tidal.search_tidal_tracks.return_value = [
            TidalSearchResult(
                track_id="999",
                title="Strobe (Sped Up)",
                artist="deadmau5",
            ),
        ]

        normalized = normalize_track("Strobe", "deadmau5")
        intent = IntentContext(
            raw_query="deadmau5 Strobe sped up",
            explicit_version_tags=["sped up"],
            wants_original=False,
        )
        result = adapter.search_track(db, tidal_user, normalized, intent)

        assert result is not None
        assert result.track_id == "999"

    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_search_no_results(self, mock_tidal, adapter, db, tidal_user):
        mock_tidal.search_tidal_tracks.return_value = []
        normalized = normalize_track("Nonexistent Track", "Unknown Artist")
        result = adapter.search_track(db, tidal_user, normalized)
        assert result is None

    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_search_all_filtered_returns_none(self, mock_tidal, adapter, db, tidal_user):
        """When all candidates are rejected by version filter, returns None."""
        mock_tidal.search_tidal_tracks.return_value = [
            TidalSearchResult(
                track_id="1",
                title="Strobe (Sped Up)",
                artist="deadmau5",
            ),
            TidalSearchResult(
                track_id="2",
                title="Strobe (Karaoke Version)",
                artist="deadmau5",
            ),
        ]

        normalized = normalize_track("Strobe", "deadmau5")
        result = adapter.search_track(db, tidal_user, normalized)
        assert result is None


class TestTidalAdapterPlaylist:
    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_ensure_playlist(self, mock_tidal, adapter, db, tidal_user, tidal_event):
        mock_tidal.create_event_playlist.return_value = "playlist_123"
        result = adapter.ensure_playlist(db, tidal_user, tidal_event)
        assert result == "playlist_123"

    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_add_to_playlist(self, mock_tidal, adapter, db, tidal_user):
        mock_tidal.add_track_to_playlist.return_value = True
        result = adapter.add_to_playlist(db, tidal_user, "playlist_123", "track_456")
        assert result is True


class TestTidalAdapterSyncTrack:
    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_full_sync_happy_path(self, mock_tidal, adapter, db, tidal_user, tidal_event):
        mock_tidal.search_tidal_tracks.return_value = [
            TidalSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
                tidal_url="https://tidal.com/browse/track/123",
            ),
        ]
        mock_tidal.create_event_playlist.return_value = "playlist_adapt"
        mock_tidal.add_track_to_playlist.return_value = True

        normalized = normalize_track("Strobe", "deadmau5")
        result = adapter.sync_track(db, tidal_user, tidal_event, normalized)

        assert result.status == SyncStatus.ADDED
        assert result.track_match is not None
        assert result.track_match.track_id == "123"
        assert result.playlist_id == "playlist_adapt"

    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_sync_track_not_found(self, mock_tidal, adapter, db, tidal_user, tidal_event):
        mock_tidal.search_tidal_tracks.return_value = []

        normalized = normalize_track("Nonexistent", "Nobody")
        result = adapter.sync_track(db, tidal_user, tidal_event, normalized)

        assert result.status == SyncStatus.NOT_FOUND

    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_sync_playlist_failure(self, mock_tidal, adapter, db, tidal_user, tidal_event):
        mock_tidal.search_tidal_tracks.return_value = [
            TidalSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
            ),
        ]
        mock_tidal.create_event_playlist.return_value = None

        normalized = normalize_track("Strobe", "deadmau5")
        result = adapter.sync_track(db, tidal_user, tidal_event, normalized)

        assert result.status == SyncStatus.ERROR
        assert "playlist" in result.error.lower()

    @patch("app.services.sync.tidal_adapter.tidal_service", new_callable=MagicMock)
    def test_sync_add_failure(self, mock_tidal, adapter, db, tidal_user, tidal_event):
        mock_tidal.search_tidal_tracks.return_value = [
            TidalSearchResult(
                track_id="123",
                title="Strobe",
                artist="deadmau5",
            ),
        ]
        mock_tidal.create_event_playlist.return_value = "playlist_adapt"
        mock_tidal.add_track_to_playlist.return_value = False

        normalized = normalize_track("Strobe", "deadmau5")
        result = adapter.sync_track(db, tidal_user, tidal_event, normalized)

        assert result.status == SyncStatus.ERROR
        assert "add track" in result.error.lower()
