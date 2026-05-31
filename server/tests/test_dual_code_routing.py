"""Issue #382 — guest endpoints resolve by EITHER public code (collection or join)."""

from app.models.event import Event
from app.services.event import (
    EventLookupResult,
    get_event_by_public_code_with_status,
)


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
