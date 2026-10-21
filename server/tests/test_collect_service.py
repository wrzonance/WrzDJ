import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.schemas.collect import UpdateCollectionSettings
from app.services import collect as collect_service


def _enable_collection(db, event: Event):
    now = utcnow()
    event.collection_opens_at = now - timedelta(hours=1)
    event.live_starts_at = now + timedelta(hours=1)
    event.submission_cap_per_guest = 3
    db.commit()
    db.refresh(event)


def _make_guest(db, suffix: str) -> Guest:
    g = Guest(
        token=suffix.ljust(64, "0"),
        fingerprint_hash=f"fp_{suffix}",
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


def test_collection_settings_normalize_aware_times_to_utc(db, test_event):
    previous_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/Los_Angeles"
    time.tzset()
    opens_at = datetime(2026, 1, 2, 12, 0, tzinfo=timezone(timedelta(hours=3)))

    try:
        collect_service.update_collection_settings(
            db, test_event, UpdateCollectionSettings(collection_opens_at=opens_at)
        )
    finally:
        if previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous_tz
        time.tzset()

    assert test_event.collection_opens_at == datetime(2026, 1, 2, 9, 0)


def test_upsert_profile_creates_row(db, test_event: Event):
    guest = _make_guest(db, "a")
    profile = collect_service.upsert_profile(
        db, event_id=test_event.id, guest_id=guest.id, nickname="Alex"
    )
    assert profile.nickname == "Alex"
    assert profile.submission_count == 0


def test_upsert_profile_updates_nickname(db, test_event: Event):
    guest = _make_guest(db, "a")
    collect_service.upsert_profile(db, event_id=test_event.id, guest_id=guest.id, nickname="Old")
    profile = collect_service.upsert_profile(
        db, event_id=test_event.id, guest_id=guest.id, nickname="NewName"
    )
    assert profile.nickname == "NewName"


def test_check_and_increment_submission_count_blocks_at_cap(db, test_event: Event):
    _enable_collection(db, test_event)
    guest = _make_guest(db, "a")
    for _ in range(3):
        collect_service.check_and_increment_submission_count(
            db, event=test_event, guest_id=guest.id
        )
    with pytest.raises(collect_service.SubmissionCapExceeded):
        collect_service.check_and_increment_submission_count(
            db, event=test_event, guest_id=guest.id
        )


def test_check_and_increment_allows_unlimited_when_cap_zero(db, test_event: Event):
    _enable_collection(db, test_event)
    test_event.submission_cap_per_guest = 0
    db.commit()
    guest = _make_guest(db, "a")
    for _ in range(20):
        collect_service.check_and_increment_submission_count(
            db, event=test_event, guest_id=guest.id
        )
    profile = (
        db.query(GuestProfile)
        .filter(
            GuestProfile.event_id == test_event.id,
            GuestProfile.guest_id == guest.id,
        )
        .one()
    )
    assert profile.submission_count == 20


def test_execute_bulk_review_returns_rejected_rows(db, test_event):
    from app.models.request import Request as SongRequest
    from app.models.request import RequestStatus
    from app.schemas.collect import BulkReviewRequest
    from app.services.collect import execute_bulk_review

    req = SongRequest(
        event_id=test_event.id,
        song_title="Track",
        artist="Artist",
        status=RequestStatus.NEW.value,
        dedupe_key="track-artist",
        submitted_during_collection=True,
        tidal_collection_track_id="tid-1",
    )
    db.add(req)
    db.commit()

    payload = BulkReviewRequest(action="reject_ids", request_ids=[req.id])
    accepted, rejected, accepted_rows, rejected_rows = execute_bulk_review(
        db, test_event.id, payload
    )

    assert accepted == 0
    assert rejected == 1
    assert len(rejected_rows) == 1
    assert rejected_rows[0].id == req.id
