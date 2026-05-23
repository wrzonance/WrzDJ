"""Tests for the public collect preview and leaderboard endpoints."""

from datetime import datetime, timedelta

import pytest

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest


def _enable_collection(db, event: Event):
    now = utcnow()
    event.collection_opens_at = now - timedelta(hours=1)
    event.live_starts_at = now + timedelta(hours=1)
    db.commit()
    db.refresh(event)


@pytest.fixture(autouse=True)
def _default_guest_cookie(client, db):
    """Most collect endpoints require a wrzdj_guest cookie (identity is guest_id only).

    After the 2026-05-20 collection-hardening change, the collect mutating
    endpoints also require a verified email and a valid wrzdj_human cookie.
    The default test guest is therefore pre-verified, and we issue a
    matching wrzdj_human cookie so the gate passes without an OTP roundtrip.

    See docs/RECOVERY-IP-IDENTITY.md and
    docs/superpowers/specs/2026-05-20-collection-vs-live-event-codes-design.md.
    """
    import hashlib

    from fastapi import Response

    from app.services.human_verification import COOKIE_NAME as HUMAN_COOKIE_NAME
    from app.services.human_verification import issue_human_cookie

    email = "default-test@example.com"
    guest = Guest(
        token="defaultguest" + "0" * 52,
        fingerprint_hash="fp_default",
        verified_email=email,
        email_hash=hashlib.sha256(email.encode()).hexdigest(),
        email_verified_at=utcnow(),
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(guest)
    db.commit()
    db.refresh(guest)

    # Mint a valid wrzdj_human cookie tied to this guest_id.
    helper_resp = Response()
    issue_human_cookie(helper_resp, guest.id)
    raw = helper_resp.headers.get("set-cookie", "")
    human_value = raw.split("=", 1)[1].split(";", 1)[0] if "=" in raw else ""

    client.cookies.clear()
    client.cookies.set("wrzdj_guest", guest.token)
    if human_value:
        client.cookies.set(HUMAN_COOKIE_NAME, human_value)
    return guest


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


def test_collect_submit_creates_request_in_collection_phase(client, db, test_event):
    _enable_collection(db, test_event)
    r = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={
            "song_title": "Mr. Brightside",
            "artist": "The Killers",
            "source": "spotify",
            "source_url": "https://open.spotify.com/track/abc",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] > 0

    from app.models.request import Request as SongRequest

    row = db.query(SongRequest).filter(SongRequest.id == body["id"]).one()
    assert row.submitted_during_collection is True
    assert row.status == "new"


def test_collect_submit_rejected_during_live_phase(client, db, test_event):
    # event without collection fields → phase == "live"
    r = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "A", "artist": "B", "source": "spotify"},
    )
    assert r.status_code == 409
    assert "Collection" in r.json()["detail"]


def test_collect_submit_blocked_at_cap(client, db, test_event):
    _enable_collection(db, test_event)
    test_event.submission_cap_per_guest = 2
    db.commit()
    for i in range(2):
        r = client.post(
            f"/api/public/collect/{test_event.code}/requests",
            json={"song_title": f"Song {i}", "artist": f"Artist {i}", "source": "spotify"},
        )
        assert r.status_code == 201
    r3 = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "Song 99", "artist": "Artist 99", "source": "spotify"},
    )
    assert r3.status_code == 429
    assert "Picks limit reached" in r3.json()["detail"]


def test_collect_vote_increments_count(client, db, test_event, collection_requests):
    _enable_collection(db, test_event)
    req = collection_requests[0]
    before = req.vote_count
    r = client.post(
        f"/api/public/collect/{test_event.code}/vote",
        json={"request_id": req.id},
    )
    assert r.status_code == 200
    db.refresh(req)
    assert req.vote_count == before + 1


def test_collect_vote_is_idempotent(client, db, test_event, collection_requests):
    _enable_collection(db, test_event)
    req = collection_requests[0]
    client.post(
        f"/api/public/collect/{test_event.code}/vote",
        json={"request_id": req.id},
    )
    before = db.query(type(req)).filter(type(req).id == req.id).one().vote_count
    client.post(
        f"/api/public/collect/{test_event.code}/vote",
        json={"request_id": req.id},
    )
    after = db.query(type(req)).filter(type(req).id == req.id).one().vote_count
    assert after == before


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


def test_collect_activity_log_entries_for_state_changes(client, db, test_event):
    """Submit, vote, and profile-set should each write one ActivityLog row
    tagged with the masked fingerprint so DJs can audit guest activity.
    """
    from app.models.activity_log import ActivityLog
    from app.models.request import Request as SongRequest
    from app.services.dedup import compute_dedupe_key

    _enable_collection(db, test_event)

    # 1. Submit a song.
    r = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "Log Me", "artist": "Audit", "source": "spotify"},
    )
    assert r.status_code == 201

    # 2. Vote on a DIFFERENT request (not our own — self-voting is blocked).
    key = compute_dedupe_key("Other", "Song")
    other_row = SongRequest(
        event_id=test_event.id,
        song_title="Song",
        artist="Other",
        source="spotify",
        status="new",
        dedupe_key=key,
        submitted_during_collection=True,
    )
    db.add(other_row)
    db.commit()
    db.refresh(other_row)

    r = client.post(
        f"/api/public/collect/{test_event.code}/vote",
        json={"request_id": other_row.id},
    )
    assert r.status_code == 200

    # 2b. Vote again — idempotent, should NOT create a second activity row.
    r = client.post(
        f"/api/public/collect/{test_event.code}/vote",
        json={"request_id": other_row.id},
    )
    assert r.status_code == 200

    # 3. Set a nickname.
    r = client.post(
        f"/api/public/collect/{test_event.code}/profile",
        json={"nickname": "LogTester"},
    )
    assert r.status_code == 200

    rows = (
        db.query(ActivityLog)
        .filter(ActivityLog.event_code == test_event.code)
        .filter(ActivityLog.source == "collect")
        .order_by(ActivityLog.id.asc())
        .all()
    )
    assert len(rows) == 3, (
        f"expected 3 collect activity rows, got {len(rows)}: {[r.message for r in rows]}"
    )
    assert "submitted" in rows[0].message
    assert "'Log Me'" in rows[0].message
    assert "voted" in rows[1].message
    assert "updated profile" in rows[2].message
    # Log messages reference Guest #<id>; no IP/hashed-IP tags ever appear.
    # See docs/RECOVERY-IP-IDENTITY.md.
    import re

    for row in rows:
        assert re.search(r"Guest #\d+", row.message), f"missing guest tag: {row.message}"


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


# ── Dedup tests ──────────────────────────────────────────────────────────────


def test_collect_submit_same_user_duplicate_returns_409(client, db, test_event):
    """Same fingerprint submitting the same song twice → 409."""
    _enable_collection(db, test_event)
    payload = {"song_title": "Mr. Brightside", "artist": "The Killers", "source": "spotify"}
    r1 = client.post(f"/api/public/collect/{test_event.code}/requests", json=payload)
    assert r1.status_code == 201

    r2 = client.post(f"/api/public/collect/{test_event.code}/requests", json=payload)
    assert r2.status_code == 409
    assert "already" in r2.json()["detail"].lower()


def test_collect_submit_same_user_duplicate_case_insensitive(client, db, test_event):
    """Dedup is case-insensitive: 'The Killers' == 'the killers'."""
    _enable_collection(db, test_event)
    r1 = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "Mr. Brightside", "artist": "The Killers", "source": "spotify"},
    )
    assert r1.status_code == 201

    r2 = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "mr. brightside", "artist": "the killers", "source": "spotify"},
    )
    assert r2.status_code == 409


def test_collect_submit_different_user_duplicate_auto_votes(client, db, test_event):
    """Different fingerprint submitting the same song → 200, is_duplicate=true, vote added."""
    _enable_collection(db, test_event)
    from app.models.request import Request as SongRequest
    from app.services.dedup import compute_dedupe_key

    key = compute_dedupe_key("The Killers", "Mr. Brightside")
    row = SongRequest(
        event_id=test_event.id,
        song_title="Mr. Brightside",
        artist="The Killers",
        source="spotify",
        status="new",
        dedupe_key=key,
        submitted_during_collection=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    original_votes = row.vote_count

    r = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "Mr. Brightside", "artist": "The Killers", "source": "spotify"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_duplicate"] is True
    assert body["id"] == row.id

    db.refresh(row)
    assert row.vote_count == original_votes + 1


def test_collect_submit_different_user_duplicate_no_pick_slot(client, db, test_event):
    """Duplicate submission by different user must NOT consume a pick slot."""
    _enable_collection(db, test_event)
    test_event.submission_cap_per_guest = 1
    db.commit()

    from app.models.request import Request as SongRequest
    from app.services.dedup import compute_dedupe_key

    key = compute_dedupe_key("The Killers", "Mr. Brightside")
    db.add(
        SongRequest(
            event_id=test_event.id,
            song_title="Mr. Brightside",
            artist="The Killers",
            source="spotify",
            status="new",
            dedupe_key=key,
            submitted_during_collection=True,
        )
    )
    db.commit()

    # This is a duplicate → should not consume the only pick slot
    r1 = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "Mr. Brightside", "artist": "The Killers", "source": "spotify"},
    )
    assert r1.status_code == 200
    assert r1.json()["is_duplicate"] is True

    # Now submit a genuinely new song → should succeed (pick slot still available)
    r2 = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "Somebody Told Me", "artist": "The Killers", "source": "spotify"},
    )
    assert r2.status_code == 201


def test_collect_submit_new_request_returns_is_duplicate_false(client, db, test_event):
    """Fresh submission returns is_duplicate=false."""
    _enable_collection(db, test_event)
    r = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "New Song", "artist": "New Artist", "source": "spotify"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["is_duplicate"] is False


# ── Self-vote tests ──────────────────────────────────────────────────────────


def test_collect_vote_self_vote_blocked(client, db, test_event):
    """Submitter cannot vote on their own request → 409."""
    _enable_collection(db, test_event)
    r = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "My Song", "artist": "My Artist", "source": "spotify"},
    )
    assert r.status_code == 201
    request_id = r.json()["id"]

    r2 = client.post(
        f"/api/public/collect/{test_event.code}/vote",
        json={"request_id": request_id},
    )
    assert r2.status_code == 409
    assert "own" in r2.json()["detail"].lower()


def test_collect_vote_other_user_still_works(client, db, test_event):
    """Voting on someone else's request still works normally."""
    _enable_collection(db, test_event)
    from app.models.request import Request as SongRequest
    from app.services.dedup import compute_dedupe_key

    key = compute_dedupe_key("Other Artist", "Other Song")
    row = SongRequest(
        event_id=test_event.id,
        song_title="Other Song",
        artist="Other Artist",
        source="spotify",
        status="new",
        dedupe_key=key,
        submitted_during_collection=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    r = client.post(
        f"/api/public/collect/{test_event.code}/vote",
        json={"request_id": row.id},
    )
    assert r.status_code == 200
    db.refresh(row)
    assert row.vote_count == 1


# ── Nickname uniqueness tests ──────────────────────────────────────────────


class TestNicknameUniqueness:
    """Tests for per-event nickname collision detection."""

    def _make_guest(self, db, token_suffix: str, verified: bool = False):
        """Build a guest. Always email-verified so the require_email_verified
        gate on collect endpoints lets them through — nickname uniqueness is
        an independent concern from email verification. The `verified` arg
        controls whether email_verified_at is set so 'claimed' detection works.
        """
        import hashlib

        from app.core.time import utcnow

        email = f"{token_suffix}@example.com"
        g = Guest(
            token="guest" + token_suffix.ljust(59, "0"),
            fingerprint_hash=f"fp_{token_suffix}",
            verified_email=email,
            email_hash=hashlib.sha256(email.encode()).hexdigest(),
            email_verified_at=utcnow() if verified else None,
            created_at=utcnow(),
            last_seen_at=utcnow(),
        )
        db.add(g)
        db.commit()
        db.refresh(g)
        return g

    def _human_cookie_for(self, guest_id: int) -> str:
        """Mint a wrzdj_human cookie value for the given guest_id."""
        from fastapi import Response

        from app.services.human_verification import issue_human_cookie

        resp = Response()
        issue_human_cookie(resp, guest_id)
        raw = resp.headers.get("set-cookie", "")
        return raw.split("=", 1)[1].split(";", 1)[0] if "=" in raw else ""

    def test_available_nickname_succeeds(self, client, db, test_event):
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "UniqueNick"},
        )
        assert r.status_code == 200
        assert r.json()["nickname"] == "UniqueNick"

    def test_collision_unclaimed_returns_409_claimed_false(
        self, client, db, test_event, _default_guest_cookie
    ):
        # default guest (autouse) claims "Alex"
        client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        # Mark default guest unverified-after-claim so "claimed" returns False.
        # The autouse fixture pre-verifies for gate-pass; this test specifically
        # exercises the post-claim unverified state.
        _default_guest_cookie.email_verified_at = None
        db.commit()
        # second guest tries "Alex"
        guest2 = self._make_guest(db, "two")
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
            cookies={
                "wrzdj_guest": guest2.token,
                "wrzdj_human": self._human_cookie_for(guest2.id),
            },
        )
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["code"] == "nickname_taken"
        assert body["claimed"] is False

    def test_collision_claimed_returns_409_claimed_true(self, client, db, test_event):
        # email-verified guest claims "Alex"
        verified_guest = self._make_guest(db, "verified", verified=True)
        client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
            cookies={
                "wrzdj_guest": verified_guest.token,
                "wrzdj_human": self._human_cookie_for(verified_guest.id),
            },
        )
        # second guest tries same name
        guest2 = self._make_guest(db, "two")
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
            cookies={
                "wrzdj_guest": guest2.token,
                "wrzdj_human": self._human_cookie_for(guest2.id),
            },
        )
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["code"] == "nickname_taken"
        assert body["claimed"] is True

    def test_self_collision_is_idempotent(self, client, db, test_event):
        client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        assert r.status_code == 200

    def test_collision_is_case_insensitive(self, client, db, test_event):
        client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        for variant in ["alex", "ALEX", "aLeX"]:
            g = self._make_guest(db, variant)
            r = client.post(
                f"/api/public/collect/{test_event.code}/profile",
                json={"nickname": variant},
                cookies={
                    "wrzdj_guest": g.token,
                    "wrzdj_human": self._human_cookie_for(g.id),
                },
            )
            assert r.status_code == 409, f"Expected 409 for variant '{variant}'"

    def test_race_condition_integrity_error_maps_to_409(self, client, db, test_event, monkeypatch):
        from sqlalchemy.exc import IntegrityError

        import app.api.collect as collect_api

        def raise_integrity(db, *, event_id, guest_id=None, nickname=None):
            raise IntegrityError("unique constraint", None, Exception())

        monkeypatch.setattr(collect_api, "upsert_profile", raise_integrity)

        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={"nickname": "Alex"},
        )
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["code"] == "nickname_taken"
        assert body["claimed"] is False

    def test_null_nickname_skips_uniqueness_check(self, client, db, test_event):
        r = client.post(
            f"/api/public/collect/{test_event.code}/profile",
            json={},
        )
        assert r.status_code == 200


def test_leaderboard_row_includes_enrichment_fields(client, db, test_event: Event):
    """Leaderboard rows expose bpm/musical_key/genre when set on the request."""
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    req = Request(
        event_id=test_event.id,
        song_title="Levels",
        artist="Avicii",
        source="beatport",
        status=RequestStatus.NEW.value,
        vote_count=3,
        dedupe_key="levels_avicii_enriched",
        submitted_during_collection=True,
        bpm=128.0,
        musical_key="8A",
        genre="Progressive House",
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    rows = r.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["bpm"] == 128
    assert rows[0]["musical_key"] == "8A"
    assert rows[0]["genre"] == "Progressive House"


def test_leaderboard_row_enrichment_fields_null_when_missing(client, db, test_event: Event):
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    req = Request(
        event_id=test_event.id,
        song_title="Unknown",
        artist="Someone",
        source="spotify",
        status=RequestStatus.NEW.value,
        dedupe_key="unknown_someone_collect",
        submitted_during_collection=True,
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    rows = r.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["bpm"] is None
    assert rows[0]["musical_key"] is None
    assert rows[0]["genre"] is None


def test_collect_submit_triggers_enrichment(client, db, test_event: Event):
    """Submitting a pick fires enrich_request_metadata as a background task."""
    from unittest.mock import patch

    _enable_collection(db, test_event)

    with patch("app.api.collect.enrich_request_metadata") as mock_enrich:
        r = client.post(
            f"/api/public/collect/{test_event.code}/requests",
            json={
                "song_title": "Levels",
                "artist": "Avicii",
                "source": "spotify",
            },
        )

    assert r.status_code == 201
    assert r.json()["is_duplicate"] is False
    mock_enrich.assert_called_once()
    _, request_id = mock_enrich.call_args[0]
    assert isinstance(request_id, int)


def test_my_picks_includes_enrichment_fields(
    client, db, test_event: Event, _default_guest_cookie: Guest
):
    """my_picks response populates bpm/musical_key/genre from enriched requests."""
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    req = Request(
        event_id=test_event.id,
        song_title="Levels",
        artist="Avicii",
        source="beatport",
        status=RequestStatus.NEW.value,
        dedupe_key="levels_avicii_mypicks",
        submitted_during_collection=True,
        guest_id=_default_guest_cookie.id,
        bpm=128.0,
        musical_key="8A",
        genre="Progressive House",
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/profile/me")
    assert r.status_code == 200
    submitted = r.json()["submitted"]
    assert len(submitted) == 1
    assert submitted[0]["bpm"] == 128
    assert submitted[0]["musical_key"] == "8A"
    assert submitted[0]["genre"] == "Progressive House"


# ── Enrich-preview tests ──────────────────────────────────────────────────────


def test_enrich_preview_returns_nulls_without_beatport_token(client, db, test_event: Event):
    """When the DJ has no Beatport token, all results have null bpm/key/genre."""
    _enable_collection(db, test_event)
    dj = test_event.created_by
    dj.beatport_access_token = None
    db.commit()

    r = client.post(
        f"/api/public/collect/{test_event.code}/enrich-preview",
        json={"items": [{"title": "Levels", "artist": "Avicii"}]},
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["title"] == "Levels"
    assert results[0]["artist"] == "Avicii"
    assert results[0]["bpm"] is None
    assert results[0]["key"] is None
    assert results[0]["genre"] is None


def test_enrich_preview_returns_bpm_from_beatport(client, db, test_event: Event):
    """When Beatport search returns a match, bpm/key/genre are populated."""
    from unittest.mock import MagicMock, patch

    _enable_collection(db, test_event)

    dj = test_event.created_by
    dj.beatport_access_token = "fake_token"  # nosec B106
    db.commit()

    mock_match = MagicMock()
    mock_match.title = "Levels"
    mock_match.artist = "Avicii"
    mock_match.bpm = 128
    mock_match.key = "8A"
    mock_match.genre = "Progressive House"
    mock_match.mix_name = "Original Mix"

    with (
        patch("app.api.collect.search_beatport_tracks", return_value=[mock_match]),
        patch("app.api.collect._find_best_match", return_value=mock_match),
    ):
        r = client.post(
            f"/api/public/collect/{test_event.code}/enrich-preview",
            json={"items": [{"title": "Levels", "artist": "Avicii"}]},
        )

    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["bpm"] == 128
    assert results[0]["key"] == "8A"
    assert results[0]["genre"] == "Progressive House"


def test_enrich_preview_caps_at_10_items(client, db, test_event: Event):
    """Requests with >10 items are silently capped — only first 10 processed."""
    _enable_collection(db, test_event)
    dj = test_event.created_by
    dj.beatport_access_token = None
    db.commit()

    items = [{"title": f"Song {i}", "artist": f"Artist {i}"} for i in range(15)]
    r = client.post(
        f"/api/public/collect/{test_event.code}/enrich-preview",
        json={"items": items},
    )
    assert r.status_code == 200
    assert len(r.json()["results"]) == 10


def test_enrich_preview_404_for_unknown_event(client):
    r = client.post(
        "/api/public/collect/ZZZZZZ/enrich-preview",
        json={"items": [{"title": "X", "artist": "Y"}]},
    )
    assert r.status_code == 404


def test_enrich_preview_returns_nulls_when_beatport_raises(client, db, test_event: Event):
    """When Beatport search raises an exception, result fields are null (best-effort)."""
    from unittest.mock import patch

    _enable_collection(db, test_event)
    dj = test_event.created_by
    dj.beatport_access_token = "fake_token"  # nosec B106
    db.commit()

    with patch("app.api.collect.search_beatport_tracks", side_effect=Exception("timeout")):
        r = client.post(
            f"/api/public/collect/{test_event.code}/enrich-preview",
            json={"items": [{"title": "Levels", "artist": "Avicii"}]},
        )

    assert r.status_code == 200
    result = r.json()["results"][0]
    assert result["bpm"] is None
    assert result["key"] is None
    assert result["genre"] is None


def test_leaderboard_row_requester_verified_true(client, db, test_event: Event):
    """requester_verified is True when guest has email_verified_at set."""
    from app.models.guest import Guest
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    guest = Guest(
        token="verified_leaderboard_test",
        email_verified_at=datetime(2026, 5, 1),
    )
    db.add(guest)
    db.flush()
    req = Request(
        event_id=test_event.id,
        song_title="Verified Track",
        artist="Verified Artist",
        source="spotify",
        status=RequestStatus.NEW.value,
        vote_count=2,
        dedupe_key="verified_lb_test",
        submitted_during_collection=True,
        guest_id=guest.id,
        nickname="VerifiedUser",
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    rows = r.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["requester_verified"] is True


def test_leaderboard_row_requester_verified_false_no_guest(client, db, test_event: Event):
    """requester_verified is False when request has no guest_id."""
    from app.models.request import Request, RequestStatus

    _enable_collection(db, test_event)
    req = Request(
        event_id=test_event.id,
        song_title="Anon Track",
        artist="Anon Artist",
        source="spotify",
        status=RequestStatus.NEW.value,
        vote_count=1,
        dedupe_key="anon_lb_test",
        submitted_during_collection=True,
    )
    db.add(req)
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/leaderboard?tab=all")
    assert r.status_code == 200
    rows = r.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["requester_verified"] is False


# ── Request preview tests ────────────────────────────────────────────────────


def test_collect_preview_returns_source_url(client, db, test_event, collection_requests):
    """Preview endpoint returns source + source_url for a valid request."""
    _enable_collection(db, test_event)
    req = collection_requests[0]
    req.source_url = "https://open.spotify.com/track/abc123"
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/requests/{req.id}/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "spotify"
    assert body["source_url"] == "https://open.spotify.com/track/abc123"


def test_collect_preview_null_source_url_for_manual(client, db, test_event, collection_requests):
    """Preview endpoint returns source_url=null for manual entries."""
    _enable_collection(db, test_event)
    req = collection_requests[0]
    req.source = "manual"
    req.source_url = None
    db.commit()

    r = client.get(f"/api/public/collect/{test_event.code}/requests/{req.id}/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "manual"
    assert body["source_url"] is None


def test_collect_preview_404_wrong_event(client, db, test_event, collection_requests):
    """Preview endpoint returns 404 when request belongs to a different event."""
    _enable_collection(db, test_event)
    req = collection_requests[0]

    r = client.get(f"/api/public/collect/ZZZZZZ/requests/{req.id}/preview")
    assert r.status_code == 404


def test_collect_preview_404_nonexistent_request(client, db, test_event):
    """Preview endpoint returns 404 for nonexistent request ID."""
    _enable_collection(db, test_event)

    r = client.get(f"/api/public/collect/{test_event.code}/requests/99999/preview")
    assert r.status_code == 404


def test_collect_submit_triggers_tidal_sync_when_enabled(client, db, test_event: Event):
    """Submitting when tidal_sync_enabled queues sync_collection_requests_batch."""
    from unittest.mock import patch

    from app.services.system_settings import get_system_settings

    _enable_collection(db, test_event)
    test_event.tidal_sync_enabled = True
    test_event.created_by.tidal_access_token = "fake_token"
    sys = get_system_settings(db)
    sys.tidal_enabled = True
    db.commit()

    with patch("app.api.collect.sync_collection_requests_batch") as mock_sync:
        r = client.post(
            f"/api/public/collect/{test_event.code}/requests",
            json={"song_title": "Auto Sync Song", "artist": "DJ Test", "source": "spotify"},
        )

    assert r.status_code == 201
    mock_sync.assert_called_once()


def test_collect_submit_skips_tidal_sync_when_disabled(client, db, test_event: Event):
    """Submitting when tidal_sync_enabled=False does not queue sync_collection_requests_batch."""
    from unittest.mock import patch

    _enable_collection(db, test_event)
    # tidal_sync_enabled defaults to False

    with patch("app.api.collect.sync_collection_requests_batch") as mock_sync:
        r = client.post(
            f"/api/public/collect/{test_event.code}/requests",
            json={"song_title": "No Sync Song", "artist": "DJ Test", "source": "spotify"},
        )

    assert r.status_code == 201
    mock_sync.assert_not_called()


class TestLiveJoinCodeEndpoint:
    """GET /api/public/collect/{code}/live-join-code"""

    def _force_live(self, db, event):
        event.collection_phase_override = "force_live"
        db.commit()
        db.refresh(event)

    def test_403_without_human_cookie(self, client, db, test_event):
        self._force_live(db, test_event)
        client.cookies.clear()
        r = client.get(f"/api/public/collect/{test_event.code}/live-join-code")
        assert r.status_code == 403
        body = r.json()
        assert body["detail"]["code"] == "human_verification_required"
        # Critically: no join_code leak in error body
        assert "join_code" not in str(body)

    def test_200_when_live_and_verified(self, client, db, test_event):
        # autouse _default_guest_cookie fixture in this file pre-issues
        # wrzdj_guest + wrzdj_human cookies for a verified guest.
        self._force_live(db, test_event)
        r = client.get(f"/api/public/collect/{test_event.code}/live-join-code")
        assert r.status_code == 200
        assert r.json() == {"join_code": test_event.join_code}

    def test_409_when_phase_is_collection(self, client, db, test_event):
        _enable_collection(db, test_event)
        r = client.get(f"/api/public/collect/{test_event.code}/live-join-code")
        assert r.status_code == 409

    def test_404_for_unknown_event(self, client, db, test_event):
        r = client.get("/api/public/collect/ZZZZZZ/live-join-code")
        assert r.status_code == 404
