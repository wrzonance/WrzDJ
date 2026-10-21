"""Public collection endpoint tests grouped by behavior."""

from app.models.event import Event
from tests.collect_public.helpers import _enable_collection

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


# ---------------------------------------------------------------------------
# #382: dual-code routing — collect endpoints must resolve by join_code too
# ---------------------------------------------------------------------------


def test_collect_preview_resolves_by_join_code(client, db, test_event: Event):
    """#382: the join page hits collect endpoints with join_code — must resolve."""
    _enable_collection(db, test_event)
    r = client.get(f"/api/public/collect/{test_event.join_code}")
    assert r.status_code == 200
    # The canonical collection code is echoed back, regardless of which code resolved it.
    assert r.json()["code"] == test_event.code


def test_join_config_resolves_by_join_code(client, db, test_event: Event):
    r = client.get(f"/api/public/collect/{test_event.join_code}/join-config")
    assert r.status_code == 200
    assert r.json() == {"frictionless_join": False}


def test_ensure_name_resolves_by_join_code_when_frictionless(client, db, test_event: Event):
    test_event.frictionless_join = True
    db.commit()
    r = client.post(f"/api/public/collect/{test_event.join_code}/guest/ensure-name", json={})
    assert r.status_code == 200
    assert r.json()["auto_generated"] is True


def test_ensure_name_boundary_is_flag_not_code(client, db, test_event: Event):
    """The frictionless boundary is the flag, never the code: a non-frictionless
    event reached by join_code still refuses auto-naming."""
    r = client.post(f"/api/public/collect/{test_event.join_code}/guest/ensure-name", json={})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "frictionless_disabled"
