"""Tests for the shared deduplication service."""

import hashlib
from datetime import timedelta

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request as SongRequest
from app.models.request import RequestStatus
from app.services.dedup import compute_dedupe_key, find_duplicate

# find_duplicate has no time window — dedup is per-event, period.


class TestComputeDedupeKey:
    def test_consistent_hash(self):
        key1 = compute_dedupe_key("Artist", "Title")
        key2 = compute_dedupe_key("Artist", "Title")
        assert key1 == key2

    def test_case_insensitive(self):
        key1 = compute_dedupe_key("THE KILLERS", "Mr. Brightside")
        key2 = compute_dedupe_key("the killers", "mr. brightside")
        assert key1 == key2

    def test_trims_whitespace(self):
        key1 = compute_dedupe_key("  Artist  ", "  Title  ")
        key2 = compute_dedupe_key("Artist", "Title")
        assert key1 == key2

    def test_returns_32_hex_chars(self):
        key = compute_dedupe_key("Artist", "Title")
        assert len(key) == 32
        int(key, 16)  # raises ValueError if not hex

    def test_different_songs_differ(self):
        key1 = compute_dedupe_key("Artist", "Song A")
        key2 = compute_dedupe_key("Artist", "Song B")
        assert key1 != key2

    def test_format_matches_expected(self):
        normalized = "artist:title"
        expected = hashlib.sha256(normalized.encode()).hexdigest()[:32]
        assert compute_dedupe_key("Artist", "Title") == expected


class TestFindDuplicate:
    def test_finds_existing_match(self, db, test_event):
        key = compute_dedupe_key("The Killers", "Mr. Brightside")
        db.add(
            SongRequest(
                event_id=test_event.id,
                song_title="Mr. Brightside",
                artist="The Killers",
                source="spotify",
                status=RequestStatus.NEW.value,
                dedupe_key=key,
            )
        )
        db.commit()
        result = find_duplicate(db, test_event.id, "The Killers", "Mr. Brightside")
        assert result is not None
        assert result.song_title == "Mr. Brightside"

    def test_case_insensitive_match(self, db, test_event):
        key = compute_dedupe_key("The Killers", "Mr. Brightside")
        db.add(
            SongRequest(
                event_id=test_event.id,
                song_title="Mr. Brightside",
                artist="The Killers",
                source="spotify",
                status=RequestStatus.NEW.value,
                dedupe_key=key,
            )
        )
        db.commit()
        result = find_duplicate(db, test_event.id, "THE KILLERS", "MR. BRIGHTSIDE")
        assert result is not None

    def test_no_match_different_song(self, db, test_event):
        key = compute_dedupe_key("The Killers", "Mr. Brightside")
        db.add(
            SongRequest(
                event_id=test_event.id,
                song_title="Mr. Brightside",
                artist="The Killers",
                source="spotify",
                status=RequestStatus.NEW.value,
                dedupe_key=key,
            )
        )
        db.commit()
        result = find_duplicate(db, test_event.id, "The Killers", "Somebody Told Me")
        assert result is None

    def test_finds_match_regardless_of_age(self, db, test_event):
        key = compute_dedupe_key("The Killers", "Mr. Brightside")
        old_request = SongRequest(
            event_id=test_event.id,
            song_title="Mr. Brightside",
            artist="The Killers",
            source="spotify",
            status=RequestStatus.NEW.value,
            dedupe_key=key,
            created_at=utcnow() - timedelta(days=30),
        )
        db.add(old_request)
        db.commit()
        result = find_duplicate(db, test_event.id, "The Killers", "Mr. Brightside")
        assert result is not None

    def test_no_match_different_event(self, db, test_event, test_user):
        other_event = Event(
            code="OTHER1",
            name="Other Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(other_event)
        db.commit()
        db.refresh(other_event)
        key = compute_dedupe_key("The Killers", "Mr. Brightside")
        db.add(
            SongRequest(
                event_id=other_event.id,
                song_title="Mr. Brightside",
                artist="The Killers",
                source="spotify",
                status=RequestStatus.NEW.value,
                dedupe_key=key,
            )
        )
        db.commit()
        result = find_duplicate(db, test_event.id, "The Killers", "Mr. Brightside")
        assert result is None
