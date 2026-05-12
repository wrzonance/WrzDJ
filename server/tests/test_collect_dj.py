from datetime import timedelta

from app.core.time import utcnow


def test_patch_collection_sets_dates(client, db, auth_headers, test_event):
    now = utcnow()
    payload = {
        "collection_opens_at": (now + timedelta(hours=1)).isoformat(),
        "live_starts_at": (now + timedelta(hours=3)).isoformat(),
        "submission_cap_per_guest": 10,
    }
    r = client.patch(
        f"/api/events/{test_event.code}/collection",
        json=payload,
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    db.refresh(test_event)
    assert test_event.submission_cap_per_guest == 10
    assert test_event.collection_opens_at is not None


def test_patch_collection_rejects_bad_ordering(client, auth_headers, test_event):
    now = utcnow()
    payload = {
        "collection_opens_at": (now + timedelta(days=2)).isoformat(),
        "live_starts_at": (now + timedelta(days=1)).isoformat(),
    }
    r = client.patch(
        f"/api/events/{test_event.code}/collection",
        json=payload,
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_patch_collection_requires_ownership(client, db, admin_user, test_event):
    # test_event is owned by test_user; create a different non-admin user
    from app.models.user import User
    from app.services.auth import create_access_token

    other = User(username="otherdj", password_hash="x", role="dj")
    db.add(other)
    db.commit()
    db.refresh(other)
    token = create_access_token(data={"sub": other.username, "tv": other.token_version})
    r = client.patch(
        f"/api/events/{test_event.code}/collection",
        json={"submission_cap_per_guest": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_patch_collection_override_accepted(client, db, auth_headers, test_event):
    r = client.patch(
        f"/api/events/{test_event.code}/collection",
        json={"collection_phase_override": "force_live"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    db.refresh(test_event)
    assert test_event.collection_phase_override == "force_live"


def test_patch_collection_override_bad_value(client, auth_headers, test_event):
    r = client.patch(
        f"/api/events/{test_event.code}/collection",
        json={"collection_phase_override": "skydiving"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_pending_review_returns_collection_news_sorted_by_votes(
    client, auth_headers, test_event, collection_requests
):
    r = client.get(
        f"/api/events/{test_event.code}/pending-review",
        headers=auth_headers,
    )
    assert r.status_code == 200
    rows = r.json()["requests"]
    # collection_requests fixture has vote_count 5, 2, 0
    assert [row["vote_count"] for row in rows] == [5, 2, 0]


def test_pending_review_excludes_accepted(
    client, db, auth_headers, test_event, collection_requests
):
    collection_requests[0].status = "accepted"
    db.commit()
    r = client.get(
        f"/api/events/{test_event.code}/pending-review",
        headers=auth_headers,
    )
    votes = [row["vote_count"] for row in r.json()["requests"]]
    assert 5 not in votes  # that request is now accepted


def test_pending_review_requires_ownership(client, db, test_event):
    from app.models.user import User
    from app.services.auth import create_access_token

    other = User(username="otherdj2", password_hash="x", role="dj")
    db.add(other)
    db.commit()
    db.refresh(other)
    token = create_access_token(data={"sub": other.username, "tv": other.token_version})
    r = client.get(
        f"/api/events/{test_event.code}/pending-review",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_bulk_review_accept_top_n(client, db, auth_headers, test_event, collection_requests):
    r = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "accept_top_n", "n": 2},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 2
    for row in collection_requests:
        db.refresh(row)
    statuses = sorted(r.status for r in collection_requests)
    assert statuses == ["accepted", "accepted", "new"]


def test_bulk_review_accept_threshold(client, db, auth_headers, test_event, collection_requests):
    r = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "accept_threshold", "min_votes": 3},
        headers=auth_headers,
    )
    assert r.status_code == 200
    # Only the vote_count=5 row qualifies
    assert r.json()["accepted"] == 1


def test_bulk_review_reject_remaining(client, db, auth_headers, test_event, collection_requests):
    r = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "reject_remaining"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["rejected"] == 3


def test_bulk_review_accept_ids(client, db, auth_headers, test_event, collection_requests):
    ids = [collection_requests[0].id, collection_requests[2].id]
    r = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "accept_ids", "request_ids": ids},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["accepted"] == 2


def test_bulk_review_rejects_over_200_ids(client, auth_headers, test_event):
    ids = list(range(1, 250))
    r = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "accept_ids", "request_ids": ids},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_bulk_review_bad_action(client, auth_headers, test_event):
    r = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "launch_nukes"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_get_collection_returns_settings(client, db, auth_headers, test_event):
    now = utcnow()
    test_event.collection_opens_at = now - timedelta(hours=1)
    test_event.live_starts_at = now + timedelta(hours=3)
    test_event.submission_cap_per_guest = 10
    db.commit()

    r = client.get(
        f"/api/events/{test_event.code}/collection",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["submission_cap_per_guest"] == 10
    assert body["phase"] in ("pre_announce", "collection", "live", "closed")
    assert body["collection_opens_at"] is not None


def test_get_collection_requires_ownership(client, db, test_event):
    from app.models.user import User
    from app.services.auth import create_access_token

    other = User(username="otherdj_get", password_hash="x", role="dj")
    db.add(other)
    db.commit()
    db.refresh(other)
    token = create_access_token(data={"sub": other.username, "tv": other.token_version})
    r = client.get(
        f"/api/events/{test_event.code}/collection",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_get_collection_404_for_unknown(client, auth_headers):
    r = client.get("/api/events/ZZZZZZ/collection", headers=auth_headers)
    assert r.status_code == 404


def test_patch_collection_auto_extends_expires_at(client, db, auth_headers, test_event):
    """When live_starts_at exceeds the event's default expires_at, the endpoint
    should automatically push expires_at forward instead of returning 400.

    The default event expiry is just 6 hours; a multi-day pre-event collection
    obviously needs the event to live through the full timeline.
    """
    from datetime import timedelta

    from app.core.time import utcnow

    now = utcnow()
    far_live = now + timedelta(days=5)
    r = client.patch(
        f"/api/events/{test_event.code}/collection",
        json={
            "collection_opens_at": (now + timedelta(hours=1)).isoformat(),
            "live_starts_at": far_live.isoformat(),
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    db.refresh(test_event)
    assert test_event.live_starts_at is not None
    # expires_at should now be > live_starts_at (the auto-extend applied)
    assert test_event.expires_at > test_event.live_starts_at


def test_patch_collection_tidal_sync_enabled(client, db, auth_headers, test_event):
    r = client.patch(
        f"/api/events/{test_event.code}/collection",
        json={"tidal_sync_enabled": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tidal_sync_enabled"] is True
    db.refresh(test_event)
    assert test_event.tidal_sync_enabled is True


def test_collection_settings_includes_tidal_fields(client, db, auth_headers, test_event):
    test_event.tidal_sync_enabled = True
    db.commit()
    r = client.get(f"/api/events/{test_event.code}/collection", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "tidal_sync_enabled" in body
    assert "tidal_collection_playlist_id" in body
    assert body["tidal_sync_enabled"] is True


def test_sync_collection_to_tidal_integration_disabled(
    client, db, auth_headers, test_event, collection_requests
):
    from app.services.system_settings import get_system_settings

    sys = get_system_settings(db)
    sys.tidal_enabled = False
    test_event.created_by.tidal_access_token = "fake_tidal_token"
    test_event.tidal_sync_enabled = True
    db.commit()

    r = client.post(
        f"/api/events/{test_event.code}/collection/sync-tidal",
        headers=auth_headers,
    )
    assert r.status_code == 503
    assert "unavailable" in r.json()["detail"]


def test_sync_collection_to_tidal_no_tidal_linked(
    client, db, auth_headers, test_event, collection_requests
):
    test_event.tidal_sync_enabled = True
    db.commit()
    r = client.post(
        f"/api/events/{test_event.code}/collection/sync-tidal",
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "not linked" in r.json()["detail"]


def test_sync_collection_to_tidal_sync_disabled(
    client, db, auth_headers, test_event, collection_requests
):
    test_event.created_by.tidal_access_token = "fake_tidal_token"
    # tidal_sync_enabled defaults to False — leave it
    db.commit()
    r = client.post(
        f"/api/events/{test_event.code}/collection/sync-tidal",
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "not enabled" in r.json()["detail"]


def test_sync_collection_to_tidal_queues_eligible(
    client, db, auth_headers, test_event, collection_requests
):
    test_event.created_by.tidal_access_token = "fake_tidal_token"
    test_event.tidal_sync_enabled = True
    # Mark one request as rejected — it should be excluded from the queued count
    collection_requests[2].status = "rejected"
    db.commit()

    r = client.post(
        f"/api/events/{test_event.code}/collection/sync-tidal",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    # 3 total collection requests, 1 rejected → 2 eligible
    assert body["queued"] == 2


def test_bulk_reject_queues_tidal_removal_for_synced_requests(
    client, db, auth_headers, test_event, monkeypatch
):
    from app.models.request import Request as SongRequest
    from app.models.request import RequestStatus

    req = SongRequest(
        event_id=test_event.id,
        song_title="Gone Track",
        artist="DJ X",
        status=RequestStatus.NEW.value,
        dedupe_key="gone-track",
        submitted_during_collection=True,
        tidal_collection_track_id="tid-999",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    test_event.tidal_sync_enabled = True
    test_event.tidal_collection_bidirectional = True
    db.commit()

    calls = []

    def fake_remove(db, user, event, track_ids):
        calls.append((db, user, event, track_ids))

    import app.api.events as events_module

    monkeypatch.setattr(events_module, "remove_collection_tracks_batch", fake_remove)

    resp = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "reject_ids", "request_ids": [req.id]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    _, _, _, track_ids = calls[0]
    assert "tid-999" in track_ids


def test_bulk_reject_skips_tidal_removal_when_no_track_id(
    client, db, auth_headers, test_event, monkeypatch
):
    from app.models.request import Request as SongRequest
    from app.models.request import RequestStatus

    req = SongRequest(
        event_id=test_event.id,
        song_title="Unsynced",
        artist="DJ X",
        status=RequestStatus.NEW.value,
        dedupe_key="unsynced",
        submitted_during_collection=True,
        tidal_collection_track_id=None,
    )
    db.add(req)
    db.commit()

    test_event.tidal_sync_enabled = True
    test_event.tidal_collection_bidirectional = True
    db.commit()

    calls = []

    def fake_remove(db, user, event, track_ids):
        calls.append((db, user, event, track_ids))

    import app.api.events as events_module

    monkeypatch.setattr(events_module, "remove_collection_tracks_batch", fake_remove)

    resp = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "reject_ids", "request_ids": [req.id]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(calls) == 0


def test_bulk_reject_skips_tidal_removal_when_bidirectional_disabled(
    client, db, auth_headers, test_event, monkeypatch
):
    """Bulk rejection must NOT remove from Tidal when bidirectional sync is off (the default)."""
    from app.models.request import Request as SongRequest
    from app.models.request import RequestStatus

    req = SongRequest(
        event_id=test_event.id,
        song_title="Guarded Bulk Track",
        artist="DJ BulkGuard",
        status=RequestStatus.NEW.value,
        dedupe_key="guarded-bulk-track",
        submitted_during_collection=True,
        tidal_collection_track_id="tid-888",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    test_event.tidal_sync_enabled = True
    test_event.tidal_collection_bidirectional = False  # the guard being tested
    db.commit()

    calls = []

    def fake_remove(db, user, event, track_ids):
        calls.append((db, user, event, track_ids))

    import app.api.events as events_module

    monkeypatch.setattr(events_module, "remove_collection_tracks_batch", fake_remove)

    resp = client.post(
        f"/api/events/{test_event.code}/bulk-review",
        json={"action": "reject_ids", "request_ids": [req.id]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(calls) == 0, "Tidal batch removal must not fire when bidirectional sync is disabled"


def test_sync_collection_to_tidal_empty_queued_when_all_rejected(
    client, db, auth_headers, test_event, collection_requests
):
    test_event.created_by.tidal_access_token = "fake_tidal_token"
    test_event.tidal_sync_enabled = True
    for req in collection_requests:
        req.status = "rejected"
    db.commit()

    r = client.post(
        f"/api/events/{test_event.code}/collection/sync-tidal",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["queued"] == 0


def test_collection_settings_response_includes_bidirectional(client, auth_headers, test_event):
    resp = client.get(
        f"/api/events/{test_event.code}/collection",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert "tidal_collection_bidirectional" in resp.json()
    assert resp.json()["tidal_collection_bidirectional"] is False  # default


def test_patch_collection_settings_sets_bidirectional(client, db, auth_headers, test_event):
    resp = client.patch(
        f"/api/events/{test_event.code}/collection",
        json={"tidal_collection_bidirectional": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["tidal_collection_bidirectional"] is True

    db.refresh(test_event)
    assert test_event.tidal_collection_bidirectional is True
