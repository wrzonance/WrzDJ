"""Public collection endpoint tests grouped by behavior."""

from app.models.event import Event
from tests.collect_public.helpers import _enable_collection


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


def test_collect_submit_triggers_collection_sync_when_enabled(client, db, test_event: Event):
    """Submitting when tidal_sync_enabled queues the fresh-session sync task."""
    from unittest.mock import patch

    from app.services.system_settings import get_system_settings

    _enable_collection(db, test_event)
    test_event.tidal_sync_enabled = True
    test_event.created_by.tidal_access_token = "fake_token"
    sys = get_system_settings(db)
    sys.tidal_enabled = True
    db.commit()

    with patch("app.api.collect.sync_collection_requests_with_fresh_session") as mock_sync:
        r = client.post(
            f"/api/public/collect/{test_event.code}/requests",
            json={"song_title": "Auto Sync Song", "artist": "DJ Test", "source": "spotify"},
        )

    assert r.status_code == 201
    mock_sync.assert_called_once()


def test_collect_submit_skips_collection_sync_when_disabled(client, db, test_event: Event):
    """Submitting when tidal_sync_enabled=False does not queue collection sync."""
    from unittest.mock import patch

    _enable_collection(db, test_event)
    # tidal_sync_enabled defaults to False

    with patch("app.api.collect.sync_collection_requests_with_fresh_session") as mock_sync:
        r = client.post(
            f"/api/public/collect/{test_event.code}/requests",
            json={"song_title": "No Sync Song", "artist": "DJ Test", "source": "spotify"},
        )

    assert r.status_code == 201
    mock_sync.assert_not_called()
