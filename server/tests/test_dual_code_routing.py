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


def test_get_event_stays_collection_only(client, db, test_event: Event, auth_headers):
    """GET /api/events/{code} is the DJ endpoint (leaks EventOut.id) — it must
    NOT be made canonical. A guest join_code must NOT resolve here."""
    assert client.get(f"/api/events/{test_event.code}", headers=auth_headers).status_code == 200
    # join_code must not resolve on the DJ-only get_event endpoint
    r = client.get(f"/api/events/{test_event.join_code}", headers=auth_headers)
    assert r.status_code == 404


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


def test_public_requests_resolve_by_either_code(client, db, test_event: Event):
    # Already worked by join_code; now also resolves by collection code (one resolver).
    assert client.get(f"/api/public/events/{test_event.join_code}/requests").status_code == 200
    assert client.get(f"/api/public/events/{test_event.code}/requests").status_code == 200
    assert client.get(f"/api/public/events/{test_event.join_code}/has-requested").status_code == 200
    assert client.get(f"/api/public/events/{test_event.code}/has-requested").status_code == 200


def test_public_event_endpoint_resolves_both_and_omits_id(client, db, test_event: Event):
    for code in (test_event.join_code, test_event.code):
        r = client.get(f"/api/public/events/{code}")
        assert r.status_code == 200, code
        body = r.json()
        # Serializer hygiene: the private surrogate key must never be emitted.
        assert "id" not in body
        # Exclude bools: True == 1 in Python, so avoid false positives when id=1.
        non_bool_values = [v for v in body.values() if not isinstance(v, bool)]
        assert test_event.id not in non_bool_values
        assert body["name"] == test_event.name
        assert body["collection_code"] == test_event.code
        assert body["frictionless_join"] is False
        assert body["requests_open"] is True
        assert body["phase"] in {"pre_announce", "collection", "live", "closed"}


def test_public_event_endpoint_404_and_410(client, db, test_event: Event):
    assert client.get("/api/public/events/ZZZZZZ").status_code == 404
    test_event.is_active = False
    db.commit()
    assert client.get(f"/api/public/events/{test_event.join_code}").status_code == 410


def test_get_event_requires_auth_no_id_leak(client, db, test_event: Event):
    """#382 hardening: GET /api/events/{code} must NOT serve EventOut (id +
    join_url) to unauthenticated callers holding only the collection code."""
    r = client.get(f"/api/events/{test_event.code}")
    assert r.status_code == 401


def test_get_event_owner_and_admin_ok_nonowner_404(
    client, db, test_event: Event, auth_headers, admin_headers
):
    # Owner (auth_headers == test_user, who owns test_event) → 200
    assert client.get(f"/api/events/{test_event.code}", headers=auth_headers).status_code == 200
    # Admin → 200 (can view any event)
    assert client.get(f"/api/events/{test_event.code}", headers=admin_headers).status_code == 200
    # Authenticated NON-owner, non-admin → 404 (no existence leak)
    from app.models.user import User
    from app.services.auth import create_access_token, get_password_hash

    other = User(username="otherdj", password_hash=get_password_hash("pw"), role="dj")
    db.add(other)
    db.commit()
    db.refresh(other)
    # Mint token directly (mirrors conftest auth_headers pattern)
    other_token = create_access_token(data={"sub": other.username, "tv": other.token_version})
    other_headers = {"Authorization": f"Bearer {other_token}"}
    assert client.get(f"/api/events/{test_event.code}", headers=other_headers).status_code == 404
