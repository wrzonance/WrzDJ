"""Pre-Event Voting pending-review pagination + sort (issue #478, PR 3/4).

Removes the silent 200-row cap, returns a true total computed before pagination,
and adds the shared sort contract. The default ordering stays the vote-ranked
review order (votes desc, age asc) so existing DJ muscle memory is preserved.
"""

from app.models.event import Event
from app.models.request import Request, RequestStatus


def _pending(db, event: Event, *, title="Song", votes=0, dedupe=None) -> Request:
    r = Request(
        event_id=event.id,
        song_title=title,
        artist="Artist",
        source="manual",
        status=RequestStatus.NEW.value,
        vote_count=votes,
        submitted_during_collection=True,
        dedupe_key=dedupe or f"pr_{title}",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _get(client, event, headers, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/events/{event.code}/pending-review" + (f"?{qs}" if qs else "")
    return client.get(url, headers=headers)


def test_pending_review_envelope_true_total(db, client, test_event, auth_headers):
    for i in range(5):
        _pending(db, test_event, title=f"S{i}", dedupe=f"d{i}")

    body = _get(client, test_event, auth_headers, limit=2, offset=0).json()

    assert body["total"] == 5
    assert len(body["requests"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_pending_review_offset_pages_cover_all(db, client, test_event, auth_headers):
    for i in range(5):
        _pending(db, test_event, title=f"S{i}", votes=i, dedupe=f"d{i}")

    p1 = _get(client, test_event, auth_headers, limit=2, offset=0).json()["requests"]
    p2 = _get(client, test_event, auth_headers, limit=2, offset=2).json()["requests"]
    p3 = _get(client, test_event, auth_headers, limit=2, offset=4).json()["requests"]

    ids = [r["id"] for r in p1 + p2 + p3]
    assert len(ids) == 5
    assert len(set(ids)) == 5


def test_pending_review_no_silent_cap(db, client, test_event, auth_headers):
    """Old code capped at 200 with total=len(rows); total must be the real count."""
    for i in range(50):
        _pending(db, test_event, title=f"S{i}", dedupe=f"d{i}")

    body = _get(client, test_event, auth_headers).json()  # default limit 100

    assert body["total"] == 50
    assert len(body["requests"]) == 50


def test_pending_review_default_is_review_order(db, client, test_event, auth_headers):
    low = _pending(db, test_event, title="low", votes=1, dedupe="a")
    high = _pending(db, test_event, title="high", votes=9, dedupe="b")

    body = _get(client, test_event, auth_headers).json()

    assert [r["id"] for r in body["requests"]] == [high.id, low.id]


def test_pending_review_oversized_limit_422(db, client, test_event, auth_headers):
    assert _get(client, test_event, auth_headers, limit=501).status_code == 422


def test_pending_review_sort_title_asc(db, client, test_event, auth_headers):
    z = _pending(db, test_event, title="Zoo", dedupe="a")
    a = _pending(db, test_event, title="Apple", dedupe="b")

    body = _get(client, test_event, auth_headers, sort="title").json()

    assert body["sort"] == "title"
    assert [r["id"] for r in body["requests"]] == [a.id, z.id]


def test_pending_review_sort_upvotes_asc_override(db, client, test_event, auth_headers):
    low = _pending(db, test_event, title="low", votes=1, dedupe="a")
    high = _pending(db, test_event, title="high", votes=9, dedupe="b")

    body = _get(client, test_event, auth_headers, sort="upvotes", direction="asc").json()

    assert body["direction"] == "asc"
    assert [r["id"] for r in body["requests"]] == [low.id, high.id]
