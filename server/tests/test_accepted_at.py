"""Regression tests for the request ``accepted_at`` timestamp.

Issue #478 (builds on #411). ``accepted_at`` records the first moment a request
entered ACCEPTED. It is the truthful backing field for the DJ "date accepted"
sort — a *historical fact* that must survive later status changes, unlike the
ambiguous ``updated_at`` (which moves on every metadata refresh, play, etc.).
"""

from datetime import timedelta

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.schemas.collect import BulkReviewRequest
from app.services.collect import execute_bulk_review
from app.services.request import accept_all_new_requests, update_request_status


def _new_request(db, event: Event, dedupe_key: str = "dk_accepted_at", **kw) -> Request:
    r = Request(
        event_id=event.id,
        song_title=kw.get("song_title", "Song"),
        artist=kw.get("artist", "Artist"),
        source="manual",
        status=RequestStatus.NEW.value,
        dedupe_key=dedupe_key,
        vote_count=kw.get("vote_count", 0),
        submitted_during_collection=kw.get("submitted_during_collection", False),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_new_request_has_null_accepted_at(db, test_event):
    r = _new_request(db, test_event)
    assert r.accepted_at is None


def test_accept_stamps_accepted_at(db, test_event):
    r = _new_request(db, test_event)
    before = utcnow()

    update_request_status(db, r, RequestStatus.ACCEPTED)

    assert r.accepted_at is not None
    assert r.accepted_at >= before - timedelta(seconds=1)


def test_accepted_at_none_when_never_accepted(db, test_event):
    r = _new_request(db, test_event)
    update_request_status(db, r, RequestStatus.REJECTED)
    assert r.accepted_at is None


def test_accepted_at_preserved_through_playing_and_played(db, test_event):
    r = _new_request(db, test_event)
    update_request_status(db, r, RequestStatus.ACCEPTED)
    first = r.accepted_at
    assert first is not None

    update_request_status(db, r, RequestStatus.PLAYING)
    update_request_status(db, r, RequestStatus.PLAYED)

    assert r.accepted_at == first


def test_accepted_at_preserved_on_rejection(db, test_event):
    r = _new_request(db, test_event)
    update_request_status(db, r, RequestStatus.ACCEPTED)
    first = r.accepted_at

    update_request_status(db, r, RequestStatus.REJECTED)

    assert r.accepted_at == first


def test_reaccept_after_rejection_preserves_first_accepted_at(db, test_event):
    """date accepted is the *first* accept, preserved even across re-accept."""
    r = _new_request(db, test_event)
    update_request_status(db, r, RequestStatus.ACCEPTED)
    first = r.accepted_at

    update_request_status(db, r, RequestStatus.REJECTED)
    update_request_status(db, r, RequestStatus.NEW)
    update_request_status(db, r, RequestStatus.ACCEPTED)

    assert r.accepted_at == first


def test_accept_all_new_requests_stamps_accepted_at(db, test_event):
    _new_request(db, test_event, dedupe_key="dk1")
    _new_request(db, test_event, dedupe_key="dk2")

    accepted = accept_all_new_requests(db, test_event)

    assert len(accepted) == 2
    assert all(r.accepted_at is not None for r in accepted)


def test_execute_bulk_review_accept_stamps_accepted_at(db, test_event):
    r = _new_request(db, test_event, dedupe_key="dkc", submitted_during_collection=True)
    payload = BulkReviewRequest(action="accept_ids", request_ids=[r.id])

    execute_bulk_review(db, test_event.id, payload)

    db.refresh(r)
    assert r.status == "accepted"
    assert r.accepted_at is not None


def test_request_out_exposes_accepted_at(db, client, test_event, auth_headers):
    r = _new_request(db, test_event)
    update_request_status(db, r, RequestStatus.ACCEPTED)

    resp = client.get(f"/api/events/{test_event.code}/requests", headers=auth_headers)

    assert resp.status_code == 200
    match = next(item for item in resp.json()["requests"] if item["id"] == r.id)
    assert match["accepted_at"] is not None
