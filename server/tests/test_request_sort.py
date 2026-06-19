"""DJ request-list pagination + sort contract (issue #478, PR 2/4).

GET /api/events/{code}/requests returns a paginated envelope with a true total
(independent of page length) and supports deterministic sorting across the seven
DJ-facing fields plus Best Match. Mirrors the #411 growing-window model already
used by /collect and /join.
"""

from datetime import timedelta

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request, RequestStatus


def _mk(
    db,
    event: Event,
    *,
    title="Song",
    artist="Artist",
    status=RequestStatus.NEW.value,
    votes=0,
    bpm=None,
    key=None,
    accepted_at=None,
    created_at=None,
    dedupe=None,
) -> Request:
    r = Request(
        event_id=event.id,
        song_title=title,
        artist=artist,
        source="manual",
        status=status,
        vote_count=votes,
        bpm=bpm,
        musical_key=key,
        accepted_at=accepted_at,
        created_at=created_at or utcnow(),
        dedupe_key=dedupe or f"dk_{title}_{artist}",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _get(client, event, headers, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/events/{event.code}/requests"
    if qs:
        url += f"?{qs}"
    resp = client.get(url, headers=headers)
    return resp


def test_list_returns_paginated_envelope_with_true_total(db, client, test_event, auth_headers):
    for i in range(3):
        _mk(db, test_event, title=f"S{i}", dedupe=f"d{i}")

    resp = _get(client, test_event, auth_headers, limit=2, offset=0)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["requests"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert "sort" in body and "direction" in body


def test_offset_pages_cover_all_rows_without_dup_or_skip(db, client, test_event, auth_headers):
    for i in range(5):
        _mk(db, test_event, title=f"S{i}", dedupe=f"d{i}")

    page1 = _get(client, test_event, auth_headers, limit=2, offset=0).json()["requests"]
    page2 = _get(client, test_event, auth_headers, limit=2, offset=2).json()["requests"]
    page3 = _get(client, test_event, auth_headers, limit=2, offset=4).json()["requests"]

    ids = [r["id"] for r in page1 + page2 + page3]
    assert len(ids) == 5
    assert len(set(ids)) == 5


def test_oversized_limit_rejected_422(db, client, test_event, auth_headers):
    resp = _get(client, test_event, auth_headers, limit=501)
    assert resp.status_code == 422


def test_default_sort_is_date_requested_desc(db, client, test_event, auth_headers):
    now = utcnow()
    old = _mk(db, test_event, title="old", created_at=now - timedelta(hours=2), dedupe="a")
    new = _mk(db, test_event, title="new", created_at=now, dedupe="b")

    body = _get(client, test_event, auth_headers).json()

    assert body["sort"] == "date_requested"
    assert body["direction"] == "desc"
    assert [r["id"] for r in body["requests"]] == [new.id, old.id]


def test_sort_upvotes_desc(db, client, test_event, auth_headers):
    low = _mk(db, test_event, title="low", votes=1, dedupe="a")
    high = _mk(db, test_event, title="high", votes=9, dedupe="b")

    body = _get(client, test_event, auth_headers, sort="upvotes").json()

    assert [r["id"] for r in body["requests"]] == [high.id, low.id]


def test_sort_title_asc(db, client, test_event, auth_headers):
    z = _mk(db, test_event, title="Zoo", dedupe="a")
    a = _mk(db, test_event, title="Apple", dedupe="b")

    body = _get(client, test_event, auth_headers, sort="title").json()

    assert [r["id"] for r in body["requests"]] == [a.id, z.id]


def test_sort_bpm_asc_nulls_last(db, client, test_event, auth_headers):
    fast = _mk(db, test_event, title="fast", bpm=140.0, dedupe="a")
    slow = _mk(db, test_event, title="slow", bpm=90.0, dedupe="b")
    unknown = _mk(db, test_event, title="unknown", bpm=None, dedupe="c")

    body = _get(client, test_event, auth_headers, sort="bpm").json()

    assert [r["id"] for r in body["requests"]] == [slow.id, fast.id, unknown.id]


def test_sort_key_camelot_order_nulls_last(db, client, test_event, auth_headers):
    # Camelot ordinals: 1A=2, 5A=10, 8B=17 -> ascending; null last
    k8b = _mk(db, test_event, title="k8b", key="8B", dedupe="a")
    k1a = _mk(db, test_event, title="k1a", key="1A", dedupe="b")
    k5a = _mk(db, test_event, title="k5a", key="5A", dedupe="c")
    knull = _mk(db, test_event, title="knull", key=None, dedupe="d")

    body = _get(client, test_event, auth_headers, sort="key").json()

    assert [r["id"] for r in body["requests"]] == [k1a.id, k5a.id, k8b.id, knull.id]


def test_sort_date_accepted_stable_after_later_updated_at(db, client, test_event, auth_headers):
    """date_accepted must not reorder when updated_at later moves (issue #478)."""
    now = utcnow()
    first = _mk(
        db,
        test_event,
        title="first",
        status=RequestStatus.ACCEPTED.value,
        accepted_at=now - timedelta(minutes=10),
        dedupe="a",
    )
    second = _mk(
        db,
        test_event,
        title="second",
        status=RequestStatus.ACCEPTED.value,
        accepted_at=now,
        dedupe="b",
    )

    # Simulate a later metadata refresh bumping `first`'s updated_at past `second`.
    first.updated_at = now + timedelta(minutes=5)
    db.commit()

    body = _get(client, test_event, auth_headers, sort="date_accepted").json()

    # desc by accepted_at -> second (newer accept) before first, unaffected by updated_at
    assert [r["id"] for r in body["requests"]] == [second.id, first.id]


def test_sort_best_match_attaches_scores_and_total(db, client, test_event, auth_headers):
    for i in range(3):
        _mk(db, test_event, title=f"S{i}", votes=i, dedupe=f"d{i}")

    body = _get(client, test_event, auth_headers, sort="best_match").json()

    assert body["sort"] == "best_match"
    assert body["total"] == 3
    assert all("priority_score" in r for r in body["requests"])


def test_direction_override(db, client, test_event, auth_headers):
    low = _mk(db, test_event, title="low", votes=1, dedupe="a")
    high = _mk(db, test_event, title="high", votes=9, dedupe="b")

    body = _get(client, test_event, auth_headers, sort="upvotes", direction="asc").json()

    assert body["direction"] == "asc"
    assert [r["id"] for r in body["requests"]] == [low.id, high.id]


def test_deterministic_tiebreaker_id_desc(db, client, test_event, auth_headers):
    a = _mk(db, test_event, title="tie", votes=5, dedupe="a")
    b = _mk(db, test_event, title="tie", votes=5, dedupe="b")

    body = _get(client, test_event, auth_headers, sort="upvotes").json()

    # equal votes -> newest id first
    assert [r["id"] for r in body["requests"]] == [b.id, a.id]


def test_status_counts_independent_of_limit_status_offset(db, client, test_event, auth_headers):
    """status_counts is the true per-status total for the whole event, not the
    paginated/filtered window (issue #478, Bugs 1 & 2)."""
    for i in range(5):
        _mk(db, test_event, title=f"new{i}", status=RequestStatus.NEW.value, dedupe=f"n{i}")
    for i in range(3):
        _mk(
            db,
            test_event,
            title=f"acc{i}",
            status=RequestStatus.ACCEPTED.value,
            accepted_at=utcnow(),
            dedupe=f"a{i}",
        )

    # Fetch a tiny window of the accepted filter — counts must ignore it.
    body = _get(client, test_event, auth_headers, status="accepted", limit=2, offset=0).json()

    assert body["total"] == 3  # active filter total is unchanged
    assert len(body["requests"]) == 2  # window honored
    assert body["status_counts"] == {
        "all": 8,
        "new": 5,
        "accepted": 3,
        "playing": 0,
        "played": 0,
        "rejected": 0,
    }


def test_status_counts_always_returns_all_six_keys_when_empty(db, client, test_event, auth_headers):
    """All six keys are present (0 when absent) so the dashboard never crashes."""
    body = _get(client, test_event, auth_headers).json()

    assert body["status_counts"] == {
        "all": 0,
        "new": 0,
        "accepted": 0,
        "playing": 0,
        "played": 0,
        "rejected": 0,
    }


def test_status_counts_present_for_best_match(db, client, test_event, auth_headers):
    """The best_match branch must include status_counts too (issue #478)."""
    _mk(db, test_event, title="n0", status=RequestStatus.NEW.value, dedupe="n0")
    _mk(db, test_event, title="n1", status=RequestStatus.NEW.value, dedupe="n1")
    _mk(
        db,
        test_event,
        title="p0",
        status=RequestStatus.PLAYED.value,
        dedupe="p0",
    )

    body = _get(client, test_event, auth_headers, sort="best_match").json()

    assert body["sort"] == "best_match"
    assert body["status_counts"] == {
        "all": 3,
        "new": 2,
        "accepted": 0,
        "playing": 0,
        "played": 1,
        "rejected": 0,
    }


def test_status_counts_ignores_since_filter(db, client, test_event, auth_headers):
    """status_counts is independent of the `since` incremental filter."""
    now = utcnow()
    _mk(
        db,
        test_event,
        title="old",
        status=RequestStatus.NEW.value,
        created_at=now - timedelta(hours=2),
        dedupe="old",
    )
    _mk(
        db,
        test_event,
        title="recent",
        status=RequestStatus.ACCEPTED.value,
        accepted_at=now,
        created_at=now,
        dedupe="recent",
    )

    since = (now - timedelta(minutes=30)).isoformat()
    body = _get(client, test_event, auth_headers, since=since).json()

    # `since` filters the page (only "recent" is newer), but counts see both.
    assert body["status_counts"]["all"] == 2
    assert body["status_counts"]["new"] == 1
    assert body["status_counts"]["accepted"] == 1


def test_sort_best_match_honors_direction(db, client, test_event, auth_headers):
    """best_match asc must reverse the priority order, not just relabel direction."""
    for i in range(3):
        _mk(db, test_event, title=f"S{i}", votes=i * 5, dedupe=f"d{i}")

    desc = _get(client, test_event, auth_headers, sort="best_match", direction="desc").json()
    asc = _get(client, test_event, auth_headers, sort="best_match", direction="asc").json()

    assert asc["direction"] == "asc"
    desc_ids = [r["id"] for r in desc["requests"]]
    asc_ids = [r["id"] for r in asc["requests"]]
    assert asc_ids == list(reversed(desc_ids))
