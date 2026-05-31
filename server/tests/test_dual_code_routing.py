"""Issue #382 — guest endpoints resolve by EITHER public code (collection or join)."""

from app.models.event import Event
from app.services.event import (
    EventLookupResult,
    get_event_by_public_code_with_status,
)
from app.services.event_bus import get_event_bus


def test_public_code_resolver_accepts_both_codes(db, test_event: Event):
    by_collection, s1 = get_event_by_public_code_with_status(db, test_event.code)
    by_join, s2 = get_event_by_public_code_with_status(db, test_event.join_code)
    assert by_collection is not None and by_join is not None
    assert by_collection.id == test_event.id == by_join.id
    assert s1 == EventLookupResult.FOUND
    assert s2 == EventLookupResult.FOUND


def test_public_code_resolver_is_case_insensitive(db, test_event: Event):
    ev, _ = get_event_by_public_code_with_status(db, test_event.join_code.lower())
    assert ev is not None and ev.id == test_event.id


def test_public_code_resolver_not_found(db):
    ev, status = get_event_by_public_code_with_status(db, "ZZZZZZ")
    assert ev is None
    assert status == EventLookupResult.NOT_FOUND


def test_submit_request_resolves_by_join_code(client, db, test_event: Event):
    r = client.post(
        f"/api/events/{test_event.join_code}/requests",
        json={"artist": "Daft Punk", "title": "One More Time"},
    )
    assert r.status_code == 200


def test_get_event_stays_collection_only(client, db, test_event: Event):
    """GET /api/events/{code} is the DJ endpoint (leaks EventOut.id) — it must
    NOT be made canonical. A guest join_code must NOT resolve here."""
    assert client.get(f"/api/events/{test_event.code}").status_code == 200
    assert client.get(f"/api/events/{test_event.join_code}").status_code == 404


def test_submit_via_join_code_publishes_on_event_code_channel(client, db, test_event: Event):
    """SSE channels are keyed by event.code; the stream subscribes by event.code
    after resolving join_code. So a join_code submit must publish on event.code."""
    bus = get_event_bus()
    queue = bus.subscribe(test_event.code)
    try:
        r = client.post(
            f"/api/events/{test_event.join_code}/requests",
            json={"artist": "Stardust", "title": "Music Sounds Better"},
        )
        assert r.status_code == 200
        msg = queue.get_nowait()  # raises QueueEmpty if nothing published to event.code
        assert msg["event"] == "request_created"
    finally:
        bus.unsubscribe(test_event.code, queue)
