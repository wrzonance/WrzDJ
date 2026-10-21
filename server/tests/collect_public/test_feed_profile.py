"""Public collection endpoint tests grouped by behavior."""

from app.core.time import utcnow
from app.models.event import Event
from tests.collect_public.helpers import _enable_collection, _make_collection_requests


def test_collect_preview_returns_phase(client, db, test_event: Event):
    _enable_collection(db, test_event)
    r = client.get(f"/api/public/collect/{test_event.code}")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == test_event.code
    assert body["phase"] == "collection"
    assert body["submission_cap_per_guest"] == 15


def test_collect_preview_404_for_unknown_code(client):
    r = client.get("/api/public/collect/ZZZZZZ")
    assert r.status_code == 404


def test_collect_leaderboard_empty(client, db, test_event: Event):
    _enable_collection(db, test_event)
    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard")
    assert r.status_code == 200
    body = r.json()
    assert body["requests"] == []
    assert body["total"] == 0


def test_collect_leaderboard_trending_sorts_by_votes(client, db, test_event, collection_requests):
    _enable_collection(db, test_event)
    # collection_requests fixture creates 3 requests with vote_count 5, 2, 0
    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=trending")
    assert r.status_code == 200
    votes = [row["vote_count"] for row in r.json()["requests"]]
    assert votes == sorted(votes, reverse=True)
    # vote_count 0 excluded from trending
    assert 0 not in votes


def test_collect_leaderboard_all_tab_includes_zero_votes(
    client, db, test_event, collection_requests
):
    _enable_collection(db, test_event)
    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    votes = [row["vote_count"] for row in r.json()["requests"]]
    assert 0 in votes


def test_collect_leaderboard_paginates_with_limit_and_offset(client, db, test_event):
    _enable_collection(db, test_event)
    _make_collection_requests(db, test_event, 5)

    # "all" tab sorts alphabetically → deterministic ordering across pages.
    r1 = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all&limit=2&offset=0")
    assert r1.status_code == 200
    b1 = r1.json()
    assert [row["title"] for row in b1["requests"]] == ["Song 000", "Song 001"]
    assert b1["total"] == 5

    r2 = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all&limit=2&offset=2")
    b2 = r2.json()
    assert [row["title"] for row in b2["requests"]] == ["Song 002", "Song 003"]
    assert b2["total"] == 5

    # Final partial page: one row left, total still reports the full set.
    r3 = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all&limit=2&offset=4")
    b3 = r3.json()
    assert [row["title"] for row in b3["requests"]] == ["Song 004"]
    assert b3["total"] == 5


def test_collect_leaderboard_total_reflects_full_count_beyond_page(client, db, test_event):
    """Regression: total is the full DB count, not the size of the returned page.

    The endpoint previously hard-capped at `.limit(200).all()` and returned
    `total=len(rows)`, so any submission past the cap was invisible AND the
    reported total silently froze at the cap. Pin the fixed behavior.
    """
    _enable_collection(db, test_event)
    _make_collection_requests(db, test_event, 7)
    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all&limit=3")
    assert r.status_code == 200
    body = r.json()
    assert len(body["requests"]) == 3
    assert body["total"] == 7


def test_collect_leaderboard_rejects_oversized_limit(client, db, test_event):
    _enable_collection(db, test_event)
    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?limit=99999")
    assert r.status_code == 422


def test_collect_leaderboard_tiebreaker_orders_by_id_desc(client, db, test_event):
    """Equal-title rows on the 'all' tab order by id desc so offset pages stay
    stable (no dup/skip). Pins the CodeRabbit pagination finding."""
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    same_time = utcnow()
    ids = []
    for i in range(3):
        r = Request(
            event_id=test_event.id,
            song_title="Same Title",
            artist=f"Artist {i}",
            source="spotify",
            status=RequestStatus.NEW.value,
            vote_count=0,
            dedupe_key=f"tie_dk_{i}",
            submitted_during_collection=True,
            created_at=same_time,
        )
        db.add(r)
        db.flush()
        ids.append(r.id)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    returned = [row["id"] for row in r.json()["requests"]]
    assert returned == sorted(ids, reverse=True)


def test_collect_profile_set_nickname(client, db, test_event):
    _enable_collection(db, test_event)
    r = client.post(
        f"/api/public/collect/{test_event.code}/profile",
        json={"nickname": "DancingQueen"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["nickname"] == "DancingQueen"
    assert body["email_verified"] is True
    assert body["submission_count"] == 0
    assert body["submission_cap"] == 15


def test_collect_profile_invalid_nickname_rejected(client, db, test_event):
    _enable_collection(db, test_event)
    r = client.post(
        f"/api/public/collect/{test_event.code}/profile",
        json={"nickname": "<script>alert(1)</script>"},
    )
    assert r.status_code == 422


def test_collect_profile_email_field_ignored(client, db, test_event):
    """Email is no longer accepted in the profile payload — extra fields are ignored."""
    _enable_collection(db, test_event)
    r = client.post(
        f"/api/public/collect/{test_event.code}/profile",
        json={"nickname": "AJ"},
    )
    assert r.status_code == 200
    assert r.json()["email_verified"] is True


def test_collect_profile_me_empty_when_no_interactions(client, db, test_event):
    _enable_collection(db, test_event)
    r = client.get(f"/api/public/collect/{test_event.code}/profile/me")
    assert r.status_code == 200
    body = r.json()
    assert body["submitted"] == []
    assert body["upvoted"] == []
    assert body["is_top_contributor"] is False


def test_collect_leaderboard_all_tab_sorts_alphabetically(client, db, test_event):
    """The All tab should sort alphabetically (case-insensitive) by song title
    so guests can scan and upvote existing submissions without recency bias.
    """
    from datetime import timedelta

    from app.core.time import utcnow
    from app.models.request import Request as SongRequest
    from app.models.request import RequestStatus

    _enable_collection(db, test_event)
    now = utcnow()
    # Intentionally insert out of order, with mixed casing.
    for idx, title in enumerate(["zebra stripes", "Alpha Song", "mango tango"]):
        db.add(
            SongRequest(
                event_id=test_event.id,
                song_title=title,
                artist=f"Artist {idx}",
                source="spotify",
                status=RequestStatus.NEW.value,
                vote_count=0,
                dedupe_key=f"dk_alpha_{idx}",
                submitted_during_collection=True,
                created_at=now - timedelta(seconds=idx),
            )
        )
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    titles = [row["title"] for row in r.json()["requests"]]
    assert titles == ["Alpha Song", "mango tango", "zebra stripes"]


def test_collect_self_vote_blocked_not_in_voted_ids(client, db, test_event):
    """Self-voting is blocked, so voted_request_ids should not include
    own submissions (since the vote was rejected).
    """
    _enable_collection(db, test_event)

    target = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "My Song", "artist": "My Artist", "source": "spotify"},
    )
    assert target.status_code == 201
    target_id = target.json()["id"]

    # Self-vote should be rejected.
    r = client.post(
        f"/api/public/collect/{test_event.code}/vote",
        json={"request_id": target_id},
    )
    assert r.status_code == 409

    me = client.get(f"/api/public/collect/{test_event.code}/profile/me")
    assert me.status_code == 200
    body = me.json()

    assert any(s["id"] == target_id for s in body["submitted"])
    assert target_id not in body["voted_request_ids"]


def test_collect_get_profile_does_not_create_row(client, db, test_event):
    """GET /profile returns defaults without creating a GuestProfile row —
    reads should not have write side effects, and ActivityLog must stay clean.
    """
    from app.models.activity_log import ActivityLog
    from app.models.guest_profile import GuestProfile

    _enable_collection(db, test_event)

    before_rows = db.query(GuestProfile).count()
    before_log = db.query(ActivityLog).count()

    r = client.get(f"/api/public/collect/{test_event.code}/profile")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "nickname": None,
        "email_verified": True,
        "submission_count": 0,
        "submission_cap": test_event.submission_cap_per_guest,
    }

    assert db.query(GuestProfile).count() == before_rows, (
        "GET /profile must not create a GuestProfile row"
    )
    assert db.query(ActivityLog).count() == before_log, "GET /profile must not write to ActivityLog"


def test_collect_get_profile_returns_existing_state(client, db, test_event):
    """When a GuestProfile exists, GET returns its fields faithfully."""
    _enable_collection(db, test_event)

    # POST a nickname first.
    r = client.post(
        f"/api/public/collect/{test_event.code}/profile",
        json={"nickname": "Reader"},
    )
    assert r.status_code == 200

    # Now read it back via GET.
    r = client.get(f"/api/public/collect/{test_event.code}/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["nickname"] == "Reader"
    assert body["email_verified"] is True
    assert body["submission_cap"] == test_event.submission_cap_per_guest
