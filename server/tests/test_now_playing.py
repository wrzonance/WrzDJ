"""Tests for now_playing service functions."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

# Re-export UTC for tests
__all__ = ["UTC"]


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


from app.models.event import Event
from app.models.now_playing import NowPlaying
from app.models.play_history import PlayHistory
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.now_playing import (
    NOW_PLAYING_AUTO_HIDE_MINUTES,
    archive_to_history,
    clear_manual_now_playing,
    clear_now_playing,
    fuzzy_match_pending_request,
    fuzzy_match_score,
    get_manual_hide_setting,
    get_next_play_order,
    get_now_playing,
    get_play_history,
    handle_now_playing_update,
    is_now_playing_hidden,
    normalize_artist,
    normalize_track_title,
    set_manual_now_playing,
    set_now_playing_visibility,
    update_bridge_status,
)


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user."""
    user = User(
        username="testuser",
        password_hash=get_password_hash("testpassword123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_event(db: Session, test_user: User) -> Event:
    """Create a test event."""
    event = Event(
        code="TEST01",
        join_code="TEST01J",
        name="Test Event",
        created_by_user_id=test_user.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@pytest.fixture
def accepted_request(db: Session, test_event: Event) -> Request:
    """Create an accepted request."""
    request = Request(
        event_id=test_event.id,
        song_title="Blue Monday",
        artist="New Order",
        source="spotify",
        status=RequestStatus.ACCEPTED.value,
        dedupe_key="test_dedupe_key_12345678",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


class TestFuzzyMatchScore:
    """Tests for fuzzy_match_score function."""

    def test_exact_match(self):
        """Exact matches return 1.0."""
        assert fuzzy_match_score("Blue Monday", "Blue Monday") == 1.0

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        assert fuzzy_match_score("BLUE MONDAY", "blue monday") == 1.0

    def test_whitespace_trimmed(self):
        """Leading/trailing whitespace is trimmed."""
        assert fuzzy_match_score("  Blue Monday  ", "Blue Monday") == 1.0

    def test_partial_match(self):
        """Similar strings return scores above 0.5."""
        score = fuzzy_match_score("Blue Monday", "Blue Monday (Original)")
        assert 0.5 < score < 1.0

    def test_no_match(self):
        """Completely different strings return low scores."""
        score = fuzzy_match_score("Blue Monday", "Sandstorm")
        assert score < 0.3


class TestNormalizeTrackTitle:
    """Tests for normalize_track_title function."""

    def test_strips_original_mix(self):
        assert normalize_track_title("Banana (Original Mix)") == "Banana"

    def test_strips_extended_mix(self):
        assert normalize_track_title("Banana (Extended Mix)") == "Banana"

    def test_strips_radio_edit(self):
        assert normalize_track_title("Banana (Radio Edit)") == "Banana"

    def test_strips_club_mix(self):
        assert normalize_track_title("Banana (Club Mix)") == "Banana"

    def test_strips_album_version(self):
        assert normalize_track_title("Banana (Album Version)") == "Banana"

    def test_strips_single_version(self):
        assert normalize_track_title("Banana (Single Version)") == "Banana"

    def test_strips_full_length(self):
        assert normalize_track_title("Banana (Full Length)") == "Banana"

    def test_strips_full_length_version(self):
        assert normalize_track_title("Banana (Full Length Version)") == "Banana"

    def test_strips_main_mix(self):
        assert normalize_track_title("Banana (Main Mix)") == "Banana"

    def test_strips_short_edit(self):
        assert normalize_track_title("Banana (Short Edit)") == "Banana"

    def test_strips_long_mix(self):
        assert normalize_track_title("Banana (Long Mix)") == "Banana"

    def test_strips_original_version(self):
        assert normalize_track_title("Banana (Original Version)") == "Banana"

    def test_strips_bare_original(self):
        assert normalize_track_title("Banana (Original)") == "Banana"

    def test_strips_bare_extended(self):
        assert normalize_track_title("Banana (Extended)") == "Banana"

    def test_strips_bracket_variant(self):
        assert normalize_track_title("Banana [Original Mix]") == "Banana"

    def test_strips_dash_radio_edit(self):
        assert normalize_track_title("Banana - Radio Edit") == "Banana"

    def test_strips_dash_original_mix(self):
        assert normalize_track_title("Banana - Original Mix") == "Banana"

    def test_case_insensitive(self):
        assert normalize_track_title("Banana (ORIGINAL MIX)") == "Banana"
        assert normalize_track_title("Banana (original mix)") == "Banana"

    def test_keeps_named_remix(self):
        assert normalize_track_title("Banana (Skrillex Remix)") == "Banana (Skrillex Remix)"

    def test_keeps_vip(self):
        assert normalize_track_title("Banana (VIP)") == "Banana (VIP)"

    def test_keeps_instrumental(self):
        assert normalize_track_title("Banana (Instrumental)") == "Banana (Instrumental)"

    def test_keeps_acoustic(self):
        assert normalize_track_title("Banana (Acoustic)") == "Banana (Acoustic)"

    def test_keeps_live(self):
        assert normalize_track_title("Banana (Live)") == "Banana (Live)"

    def test_keeps_dub_mix(self):
        assert normalize_track_title("Banana (Dub Mix)") == "Banana (Dub Mix)"

    def test_keeps_a_cappella(self):
        assert normalize_track_title("Banana (A Cappella)") == "Banana (A Cappella)"

    def test_keeps_remaster(self):
        assert normalize_track_title("Banana (2024 Remaster)") == "Banana (2024 Remaster)"

    def test_empty_string(self):
        assert normalize_track_title("") == ""

    def test_whitespace_only(self):
        assert normalize_track_title("   ") == ""

    def test_no_suffix(self):
        assert normalize_track_title("Just a Song") == "Just a Song"

    def test_multiple_parenthetical_strips_generic_only(self):
        result = normalize_track_title("Banana (Skrillex Remix) (Original Mix)")
        assert result == "Banana (Skrillex Remix)"


class TestNormalizeArtist:
    """Tests for normalize_artist function."""

    def test_normalizes_featuring(self):
        assert normalize_artist("Drake featuring Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_feat_no_dot(self):
        assert normalize_artist("Drake feat Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_feat_dot(self):
        assert normalize_artist("Drake feat. Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_ft_no_dot(self):
        assert normalize_artist("Drake ft Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_ft_dot(self):
        assert normalize_artist("Drake ft. Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_with(self):
        assert normalize_artist("Drake with Rihanna") == "Drake feat. Rihanna"

    def test_normalizes_capitalized(self):
        assert normalize_artist("Drake Featuring Rihanna") == "Drake feat. Rihanna"

    def test_no_false_positive_daft(self):
        """Should not match 'ft' inside words like 'Daft'."""
        assert normalize_artist("Daft Punk") == "Daft Punk"

    def test_empty_string(self):
        assert normalize_artist("") == ""

    def test_whitespace_only(self):
        assert normalize_artist("   ") == ""

    def test_no_featuring(self):
        assert normalize_artist("New Order") == "New Order"


class TestFuzzyMatchPendingRequest:
    """Tests for fuzzy_match_pending_request function."""

    def test_exact_match(self, db: Session, test_event: Event, accepted_request: Request):
        """Finds exact match in accepted requests."""
        result = fuzzy_match_pending_request(db, test_event.id, "Blue Monday", "New Order")
        assert result is not None
        assert result.id == accepted_request.id

    def test_match_with_original_mix_suffix(
        self, db: Session, test_event: Event, accepted_request: Request
    ):
        """Matches when DJ equipment reports '(Original Mix)' suffix."""
        result = fuzzy_match_pending_request(
            db, test_event.id, "Blue Monday (Original Mix)", "New Order"
        )
        assert result is not None
        assert result.id == accepted_request.id

    def test_match_with_extended_mix_suffix(
        self, db: Session, test_event: Event, accepted_request: Request
    ):
        """Matches when DJ equipment reports '(Extended Mix)' suffix."""
        result = fuzzy_match_pending_request(
            db, test_event.id, "Blue Monday (Extended Mix)", "New Order"
        )
        assert result is not None
        assert result.id == accepted_request.id

    def test_match_with_dash_radio_edit(
        self, db: Session, test_event: Event, accepted_request: Request
    ):
        """Matches when DJ equipment reports '- Radio Edit' suffix."""
        result = fuzzy_match_pending_request(
            db, test_event.id, "Blue Monday - Radio Edit", "New Order"
        )
        assert result is not None
        assert result.id == accepted_request.id

    def test_no_match_named_remix(self, db: Session, test_event: Event, accepted_request: Request):
        """Does NOT match when it's a genuinely different version (named remix)."""
        result = fuzzy_match_pending_request(
            db, test_event.id, "Blue Monday (Hardfloor Remix)", "New Order"
        )
        # Named remix changes the title enough that it shouldn't match "Blue Monday"
        # (fuzzy score of normalized titles will differ)
        assert result is None

    def test_match_feat_vs_featuring(self, db: Session, test_event: Event):
        """Matches artist with 'feat.' vs 'featuring'."""
        req = Request(
            event_id=test_event.id,
            song_title="One Dance",
            artist="Drake featuring Wizkid",
            source="spotify",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="feat_test_key",
        )
        db.add(req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "One Dance", "Drake feat. Wizkid")
        assert result is not None
        assert result.id == req.id

    def test_matches_new_requests(self, db: Session, test_event: Event):
        """Matches NEW requests (not just ACCEPTED)."""
        new_req = Request(
            event_id=test_event.id,
            song_title="Sandstorm",
            artist="Darude",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="new_req_key",
        )
        db.add(new_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is not None
        assert result.id == new_req.id

    def test_prefers_accepted_over_new(self, db: Session, test_event: Event):
        """Prefers ACCEPTED over NEW when both match equally."""
        new_req = Request(
            event_id=test_event.id,
            song_title="Levels",
            artist="Avicii",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key="levels_new_key",
        )
        accepted_req = Request(
            event_id=test_event.id,
            song_title="Levels",
            artist="Avicii",
            source="spotify",
            status=RequestStatus.ACCEPTED.value,
            dedupe_key="levels_accepted_key",
        )
        db.add(new_req)
        db.add(accepted_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Levels", "Avicii")
        assert result is not None
        assert result.id == accepted_req.id

    def test_does_not_match_playing(self, db: Session, test_event: Event):
        """Does not match PLAYING requests."""
        playing_req = Request(
            event_id=test_event.id,
            song_title="Sandstorm",
            artist="Darude",
            status=RequestStatus.PLAYING.value,
            dedupe_key="playing_key",
        )
        db.add(playing_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is None

    def test_does_not_match_played(self, db: Session, test_event: Event):
        """Does not match PLAYED requests."""
        played_req = Request(
            event_id=test_event.id,
            song_title="Sandstorm",
            artist="Darude",
            status=RequestStatus.PLAYED.value,
            dedupe_key="played_key",
        )
        db.add(played_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is None

    def test_does_not_match_rejected(self, db: Session, test_event: Event):
        """Does not match REJECTED requests."""
        rejected_req = Request(
            event_id=test_event.id,
            song_title="Sandstorm",
            artist="Darude",
            status=RequestStatus.REJECTED.value,
            dedupe_key="rejected_key",
        )
        db.add(rejected_req)
        db.commit()

        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is None

    def test_no_match_below_threshold(
        self, db: Session, test_event: Event, accepted_request: Request
    ):
        """Returns None when no match above threshold."""
        result = fuzzy_match_pending_request(db, test_event.id, "Sandstorm", "Darude")
        assert result is None


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
    """Tests for handle_now_playing_update function."""

    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_creates_now_playing(self, mock_spotify, db: Session, test_event: Event):
        """Creates a new now_playing record."""
        mock_spotify.return_value = None

        result = handle_now_playing_update(
            db, "TEST01", "New Track", "New Artist", "Test Album", "1"
        )

        assert result is not None
        assert result.title == "New Track"
        assert result.artist == "New Artist"
        assert result.album == "Test Album"
        assert result.deck == "1"
        assert result.source == "bridge"

    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_archives_previous_track(self, mock_spotify, db: Session, test_event: Event):
        """Archives previous track when new track arrives."""
        mock_spotify.return_value = None

        # First track
        handle_now_playing_update(db, "TEST01", "First Track", "First Artist")

        # Second track should archive the first
        handle_now_playing_update(db, "TEST01", "Second Track", "Second Artist")

        # Check history
        items, total = get_play_history(db, test_event.id)
        assert total == 1
        assert items[0].title == "First Track"
        assert items[0].ended_at is not None

    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_auto_matches_request(
        self, mock_spotify, db: Session, test_event: Event, accepted_request: Request
    ):
        """Auto-matches accepted requests."""
        mock_spotify.return_value = None

        result = handle_now_playing_update(db, "TEST01", "Blue Monday", "New Order")

        # Check request was matched
        db.refresh(accepted_request)
        assert accepted_request.status == RequestStatus.PLAYING.value
        assert result.matched_request_id == accepted_request.id

    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_transitions_request_to_played(
        self, mock_spotify, db: Session, test_event: Event, accepted_request: Request
    ):
        """Transitions matched request to played when next track arrives."""
        mock_spotify.return_value = None

        # First track matches request
        handle_now_playing_update(db, "TEST01", "Blue Monday", "New Order")

        # Second track should transition request to played
        handle_now_playing_update(db, "TEST01", "Sandstorm", "Darude")

        db.refresh(accepted_request)
        assert accepted_request.status == RequestStatus.PLAYED.value

    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_adds_spotify_data(self, mock_spotify, db: Session, test_event: Event):
        """Adds Spotify album art data."""
        mock_spotify.return_value = {
            "spotify_track_id": "sp123",
            "album_art_url": "https://example.com/art.jpg",
            "spotify_uri": "spotify:track:sp123",
        }

        result = handle_now_playing_update(db, "TEST01", "Test Track", "Test Artist")

        assert result.spotify_track_id == "sp123"
        assert result.album_art_url == "https://example.com/art.jpg"
        assert result.spotify_uri == "spotify:track:sp123"

    def test_event_not_found(self, db: Session):
        """Returns None for non-existent event."""
        result = handle_now_playing_update(db, "INVALID", "Test", "Test")
        assert result is None


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


class TestClearNowPlaying:
    """Tests for clear_now_playing function."""

    @patch("app.services.now_playing.lookup_spotify_album_art")
    def test_archives_and_clears(self, mock_spotify, db: Session, test_event: Event):
        """Archives current track and clears now_playing."""
        mock_spotify.return_value = None

        # Set up now_playing
        handle_now_playing_update(db, "TEST01", "Test Track", "Test Artist")

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
        handle_now_playing_update(db, "TEST01", "Bridge Track", "Bridge Artist")

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
        handle_now_playing_update(db, "TEST01", "Bridge Track", "Bridge Artist")

        db.refresh(req1)
        db.refresh(req2)
        assert req1.status == RequestStatus.PLAYED.value
        assert req2.status == RequestStatus.PLAYED.value
