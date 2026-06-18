"""Kiosk display pagination (issue #478, PR 4/4).

GET /api/public/events/{join_code}/display previously returned every accepted
row (sorted in Python over event.requests) with no true total. Add limit/offset
+ accepted_queue_total so the kiosk can grow its window and show a truthful
queue count instead of treating the visible page as the whole queue.
"""

from app.models.event import Event
from app.models.request import Request, RequestStatus


def _accepted(db, event: Event, *, title="Song", votes=0, dedupe=None) -> Request:
    r = Request(
        event_id=event.id,
        song_title=title,
        artist="Artist",
        source="manual",
        status=RequestStatus.ACCEPTED.value,
        vote_count=votes,
        dedupe_key=dedupe or f"kd_{title}",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _get(client, event: Event, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/public/events/{event.join_code}/display" + (f"?{qs}" if qs else "")
    return client.get(url)


def test_kiosk_display_reports_true_accepted_total(db, client, test_event):
    for i in range(5):
        _accepted(db, test_event, title=f"S{i}", dedupe=f"d{i}")

    body = _get(client, test_event, limit=2, offset=0).json()

    assert body["accepted_queue_total"] == 5
    assert len(body["accepted_queue"]) == 2


def test_kiosk_display_offset_pages_cover_all(db, client, test_event):
    for i in range(4):
        _accepted(db, test_event, title=f"S{i}", votes=10 - i, dedupe=f"d{i}")

    p1 = _get(client, test_event, limit=2, offset=0).json()["accepted_queue"]
    p2 = _get(client, test_event, limit=2, offset=2).json()["accepted_queue"]

    ids = [r["id"] for r in p1 + p2]
    assert len(ids) == 4
    assert len(set(ids)) == 4


def test_kiosk_display_order_votes_desc(db, client, test_event):
    low = _accepted(db, test_event, title="low", votes=1, dedupe="a")
    high = _accepted(db, test_event, title="high", votes=9, dedupe="b")

    body = _get(client, test_event).json()

    assert [r["id"] for r in body["accepted_queue"]] == [high.id, low.id]


def test_kiosk_display_total_counts_all_not_page(db, client, test_event):
    for i in range(30):
        _accepted(db, test_event, title=f"S{i}", dedupe=f"d{i}")

    body = _get(client, test_event, limit=10).json()

    assert body["accepted_queue_total"] == 30
    assert len(body["accepted_queue"]) == 10


def test_kiosk_display_oversized_limit_422(db, client, test_event):
    assert _get(client, test_event, limit=501).status_code == 422
