"""Now-playing service tests grouped by lifecycle behavior."""

from datetime import UTC, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.now_playing import NowPlaying
from app.models.play_history import PlayHistory
from app.services.bridge_integration import (
    clear_now_playing,
    sync_now_playing_from_bridge,
    update_bridge_status,
)
from app.services.now_playing import (
    NOW_PLAYING_AUTO_HIDE_MINUTES,
    get_manual_hide_setting,
    get_now_playing,
    get_play_history,
    is_now_playing_hidden,
    set_now_playing_visibility,
)
from tests.now_playing.helpers import utcnow


class TestUpdateBridgeStatus:
    """Tests for update_bridge_status function."""

    def test_updates_status(self, db: Session, test_event: Event):
        """Updates bridge connection status."""
        success = update_bridge_status(db, "TEST01", True, "SC6000")

        assert success
        now_playing = get_now_playing(db, test_event.id)
        assert now_playing.bridge_connected is True
        assert now_playing.bridge_device_name == "SC6000"
        assert now_playing.bridge_last_seen is not None

    def test_creates_placeholder_if_needed(self, db: Session, test_event: Event):
        """Creates placeholder now_playing if none exists."""
        success = update_bridge_status(db, "TEST01", True, "Prime 4")

        assert success
        now_playing = get_now_playing(db, test_event.id)
        assert now_playing is not None
        assert now_playing.title == ""  # Placeholder
        assert now_playing.bridge_connected is True

    def test_event_not_found(self, db: Session):
        """Returns False for non-existent event."""
        success = update_bridge_status(db, "INVALID", True)
        assert success is False

    def test_activity_log_failure_propagates(self, db: Session, test_event: Event, monkeypatch):
        """A failed activity write prevents committing a partial bridge update."""
        import app.services.activity_log as activity_log

        def fail(*args, **kwargs):
            raise RuntimeError("activity database unavailable")

        monkeypatch.setattr(activity_log, "log_activity", fail)

        with pytest.raises(RuntimeError, match="activity database unavailable"):
            update_bridge_status(db, "TEST01", True, "SC6000")

        assert db.query(NowPlaying).filter(NowPlaying.event_id == test_event.id).first() is None


class TestClearNowPlaying:
    """Tests for clear_now_playing function."""

    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_archives_and_clears(self, mock_spotify, db: Session, test_event: Event):
        """Archives current track and clears now_playing."""
        mock_spotify.return_value = None

        # Set up now_playing
        sync_now_playing_from_bridge(db, "TEST01", "Test Track", "Test Artist")

        # Clear it
        success = clear_now_playing(db, "TEST01")

        assert success
        now_playing = get_now_playing(db, test_event.id)
        assert now_playing.title == ""  # Cleared

        # Check history
        items, _ = get_play_history(db, test_event.id)
        assert len(items) == 1
        assert items[0].title == "Test Track"


class TestGetPlayHistory:
    """Tests for get_play_history function."""

    def test_returns_empty_for_no_history(self, db: Session, test_event: Event):
        """Returns empty list when no history."""
        items, total = get_play_history(db, test_event.id)
        assert items == []
        assert total == 0

    def test_returns_history_newest_first(self, db: Session, test_event: Event):
        """Returns history ordered by play_order descending."""
        # Add history
        for i in range(5):
            history = PlayHistory(
                event_id=test_event.id,
                title=f"Track {i + 1}",
                artist="Artist",
                started_at=utcnow(),
                play_order=i + 1,
            )
            db.add(history)
        db.commit()

        items, total = get_play_history(db, test_event.id)
        assert total == 5
        assert len(items) == 5
        assert items[0].title == "Track 5"  # Newest first
        assert items[4].title == "Track 1"

    def test_pagination(self, db: Session, test_event: Event):
        """Supports pagination."""
        # Add history
        for i in range(10):
            history = PlayHistory(
                event_id=test_event.id,
                title=f"Track {i + 1}",
                artist="Artist",
                started_at=utcnow(),
                play_order=i + 1,
            )
            db.add(history)
        db.commit()

        # Get page 2 (offset=3, limit=3)
        items, total = get_play_history(db, test_event.id, limit=3, offset=3)
        assert total == 10
        assert len(items) == 3
        assert items[0].title == "Track 7"  # 10, 9, 8, [7, 6, 5]


class TestIsNowPlayingHidden:
    """Tests for is_now_playing_hidden function."""

    def test_hidden_when_no_now_playing(self, db: Session, test_event: Event):
        """Hidden when no now_playing record exists."""
        assert is_now_playing_hidden(db, test_event.id) is True

    def test_hidden_when_empty_title(self, db: Session, test_event: Event):
        """Hidden when now_playing has empty title."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="",
            artist="",
        )
        db.add(now_playing)
        db.commit()

        assert is_now_playing_hidden(db, test_event.id) is True

    def test_visible_with_track_playing(self, db: Session, test_event: Event):
        """Visible when track is playing."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow(),
        )
        db.add(now_playing)
        db.commit()

        assert is_now_playing_hidden(db, test_event.id) is False

    def test_hidden_when_manual_hide(self, db: Session, test_event: Event):
        """Hidden when manual_hide_now_playing is True."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow(),
            manual_hide_now_playing=True,
        )
        db.add(now_playing)
        db.commit()

        assert is_now_playing_hidden(db, test_event.id) is True

    def test_hidden_after_auto_timeout(self, db: Session, test_event: Event):
        """Hidden after default 10 minutes of inactivity."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow() - timedelta(minutes=NOW_PLAYING_AUTO_HIDE_MINUTES + 1),
        )
        db.add(now_playing)
        db.commit()

        assert is_now_playing_hidden(db, test_event.id) is True

    def test_visible_within_timeout(self, db: Session, test_event: Event):
        """Visible within default 10 minute timeout."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow() - timedelta(minutes=5),
        )
        db.add(now_playing)
        db.commit()

        assert is_now_playing_hidden(db, test_event.id) is False

    def test_last_shown_at_resets_timer(self, db: Session, test_event: Event):
        """last_shown_at resets the auto-hide timer."""
        # Track started 15 minutes ago but was shown 5 minutes ago
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow() - timedelta(minutes=15),
            last_shown_at=utcnow() - timedelta(minutes=5),
        )
        db.add(now_playing)
        db.commit()

        assert is_now_playing_hidden(db, test_event.id) is False

    def test_hidden_after_custom_auto_timeout(self, db: Session, test_event: Event):
        """Hidden after custom per-event auto-hide timeout."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow() - timedelta(minutes=6),
        )
        db.add(now_playing)
        db.commit()

        # Event with 5-minute timeout, track started 6min ago => hidden
        assert is_now_playing_hidden(db, test_event.id, auto_hide_minutes=5) is True

    def test_visible_within_custom_timeout(self, db: Session, test_event: Event):
        """Visible within custom per-event timeout."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow() - timedelta(minutes=3),
        )
        db.add(now_playing)
        db.commit()

        # Event with 5-minute timeout, track started 3min ago => visible
        assert is_now_playing_hidden(db, test_event.id, auto_hide_minutes=5) is False

    def test_bridge_last_seen_does_not_reset_timer(self, db: Session, test_event: Event):
        """bridge_last_seen does NOT reset the auto-hide timer (heartbeats ignored)."""
        # Track started 15min ago, bridge_last_seen 3min ago, default 10min timeout
        # Should be hidden because started_at is 15min ago (exceeds 10min timeout)
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow() - timedelta(minutes=15),
            bridge_last_seen=utcnow() - timedelta(minutes=3),
        )
        db.add(now_playing)
        db.commit()

        assert is_now_playing_hidden(db, test_event.id) is True


class TestGetManualHideSetting:
    """Tests for get_manual_hide_setting function."""

    def test_false_when_no_record(self, db: Session, test_event: Event):
        """Returns False (visible) when no NowPlaying record exists."""
        assert get_manual_hide_setting(db, test_event.id) is False

    def test_returns_manual_hide_value(self, db: Session, test_event: Event):
        """Returns the manual_hide_now_playing field value."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            manual_hide_now_playing=True,
        )
        db.add(now_playing)
        db.commit()
        assert get_manual_hide_setting(db, test_event.id) is True

    def test_false_with_empty_title(self, db: Session, test_event: Event):
        """Returns False even when title is empty (unlike is_now_playing_hidden).

        This is the key difference: the manual setting reflects the DJ's
        intent, not whether a track is actually playing.
        """
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="",
            artist="",
            manual_hide_now_playing=False,
        )
        db.add(now_playing)
        db.commit()
        assert get_manual_hide_setting(db, test_event.id) is False


class TestSetNowPlayingVisibility:
    """Tests for set_now_playing_visibility function."""

    def test_hide_existing_now_playing(self, db: Session, test_event: Event):
        """Can hide existing now_playing."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow(),
        )
        db.add(now_playing)
        db.commit()

        success = set_now_playing_visibility(db, test_event.id, hidden=True)

        assert success is True
        db.refresh(now_playing)
        assert now_playing.manual_hide_now_playing is True

    def test_show_hidden_now_playing(self, db: Session, test_event: Event):
        """Can show hidden now_playing and resets timer."""
        now_playing = NowPlaying(
            event_id=test_event.id,
            title="Test Track",
            artist="Test Artist",
            started_at=utcnow() - timedelta(minutes=90),
            manual_hide_now_playing=True,
        )
        db.add(now_playing)
        db.commit()

        success = set_now_playing_visibility(db, test_event.id, hidden=False)

        assert success is True
        db.refresh(now_playing)
        assert now_playing.manual_hide_now_playing is False
        assert now_playing.last_shown_at is not None
        # last_shown_at should be recent (within last few seconds)
        # Handle timezone-naive from SQLite
        last_shown = now_playing.last_shown_at
        if last_shown.tzinfo is None:
            last_shown = last_shown.replace(tzinfo=UTC)
        assert utcnow() - last_shown < timedelta(seconds=2)

    def test_creates_placeholder_when_none_exists(self, db: Session, test_event: Event):
        """Creates placeholder now_playing when none exists."""
        success = set_now_playing_visibility(db, test_event.id, hidden=True)

        assert success is True
        now_playing = get_now_playing(db, test_event.id)
        assert now_playing is not None
        assert now_playing.title == ""
        assert now_playing.manual_hide_now_playing is True
