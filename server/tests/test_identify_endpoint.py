"""Integration tests for POST /api/public/guest/identify."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.guest import Guest


def test_identify_sets_cookie(client: TestClient):
    """Response includes Set-Cookie with correct attributes."""
    resp = client.post(
        "/api/public/guest/identify",
        json={
            "fingerprint_hash": "test_fp_cookie_check",
            "fingerprint_components": {"screen": "1170x2532"},
        },
    )
    assert resp.status_code == 200
    assert "guest_id" in resp.json()

    cookie = resp.cookies.get("wrzdj_guest")
    assert cookie is not None
    assert len(cookie) == 64

    set_cookie_header = resp.headers.get("set-cookie", "")
    assert "httponly" in set_cookie_header.lower()
    assert "path=/api/" in set_cookie_header.lower()


def test_identify_with_cookie_returns_same_guest(client: TestClient):
    """Second call with cookie -> same guest_id, no new row."""
    resp1 = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "test_fp_same_guest"},
    )
    guest_id_1 = resp1.json()["guest_id"]
    cookie_val = resp1.cookies["wrzdj_guest"]

    client.cookies.set("wrzdj_guest", cookie_val)
    resp2 = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "test_fp_same_guest"},
    )
    guest_id_2 = resp2.json()["guest_id"]

    assert guest_id_1 == guest_id_2


def test_identify_without_cookie_reconciles(client: TestClient, db: Session):
    """Second call without cookie but with same fingerprint, after the quiet period
    has elapsed -> same guest (reconcile)."""
    _chrome_ua = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"
    resp1 = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "test_fp_reconcile"},
        headers={"User-Agent": _chrome_ua},
    )
    guest_id_1 = resp1.json()["guest_id"]

    # Backdate so the guest is outside the 12-hour concurrent-activity window
    g = db.query(Guest).filter(Guest.id == guest_id_1).one()
    g.last_seen_at = utcnow() - timedelta(hours=13)
    db.commit()

    client.cookies.clear()
    resp2 = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "test_fp_reconcile"},
        headers={"User-Agent": _chrome_ua},
    )
    guest_id_2 = resp2.json()["guest_id"]

    assert guest_id_1 == guest_id_2
    assert resp2.json().get("action") == "reconcile"


def test_identify_invalid_fingerprint_format(client: TestClient):
    """Malformed fingerprint_hash -> 422."""
    resp = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "short"},
    )
    assert resp.status_code == 422


def test_identify_missing_body(client: TestClient):
    """No body -> 422."""
    resp = client.post("/api/public/guest/identify")
    assert resp.status_code == 422


def test_identify_response_includes_action_create_then_cookie_hit(client):
    """F6 — response body must carry the action so the frontend can
    detect first-time creates without inspecting Set-Cookie (which is
    a forbidden cross-origin response header)."""
    first = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "fp_action_test_1", "fingerprint_components": {}},
    )
    assert first.status_code == 200
    body = first.json()
    assert "guest_id" in body
    assert body.get("action") == "create"

    # Same client (cookie persisted) hits identify again
    second = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "fp_action_test_1", "fingerprint_components": {}},
    )
    assert second.status_code == 200
    assert second.json().get("action") == "cookie_hit"
    assert second.json().get("guest_id") == body["guest_id"]


def _guest_cookie_max_age(resp) -> int:
    """Max-Age of the wrzdj_guest Set-Cookie header in a response."""
    (header,) = [h for h in resp.headers.get_list("set-cookie") if h.startswith("wrzdj_guest=")]
    attrs = dict(part.strip().split("=", 1) for part in header.split(";")[1:] if "=" in part)
    return int(attrs["Max-Age"])


def test_identify_cookie_max_age_defaults_to_24_hours(client: TestClient):
    resp = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "test_fp_max_age_default"},
    )
    assert _guest_cookie_max_age(resp) == 24 * 60 * 60


def test_identify_cookie_max_age_follows_setting(client: TestClient, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "guest_cookie_max_age_seconds", 12 * 60 * 60)
    resp = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "test_fp_max_age_setting"},
    )
    assert _guest_cookie_max_age(resp) == 12 * 60 * 60


def test_identify_cookie_hit_renews_the_same_cookie(client: TestClient):
    """A returning guest's cookie is re-set with a fresh Max-Age, so the window slides."""
    first = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "test_fp_renew"},
    )
    token = first.cookies["wrzdj_guest"]

    client.cookies.set("wrzdj_guest", token)
    second = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "test_fp_renew"},
    )

    assert second.json()["action"] == "cookie_hit"
    assert second.cookies["wrzdj_guest"] == token
    assert _guest_cookie_max_age(second) == 24 * 60 * 60


def test_identify_cookie_hit_re_sets_the_stored_token(client: TestClient, db):
    """The renewed cookie carries the guest row's stored token, not the request's value
    (#932 CodeQL: a cookie built from user-supplied input)."""
    from app.models.guest import Guest

    first = client.post("/api/public/guest/identify", json={"fingerprint_hash": "test_fp_store"})
    guest_id = first.json()["guest_id"]
    client.cookies.set("wrzdj_guest", first.cookies["wrzdj_guest"])

    second = client.post("/api/public/guest/identify", json={"fingerprint_hash": "test_fp_store"})

    assert second.json()["action"] == "cookie_hit"
    assert second.cookies["wrzdj_guest"] == db.get(Guest, guest_id).token


def _merge_two_devices(client: TestClient, db: Session, email: str) -> dict:
    """Identify devices A and B, verify the same email on both so B merges into A."""
    from tests.test_verify_endpoints import _claim_email, _identify

    device_a = _identify(client, f"race_a_{email}")
    client.cookies.set("wrzdj_guest", device_a["cookie"])
    assert _claim_email(client, db, device_a["guest_id"], email).status_code == 200
    device_b = _identify(client, f"race_b_{email}")
    client.cookies.set("wrzdj_guest", device_b["cookie"])
    resp = _claim_email(client, db, device_b["guest_id"], email)
    assert resp.json()["merged"] is True
    return {"survivor": device_a, "stale_token": device_b["cookie"]}


def test_identify_with_stale_merged_cookie_reissues_survivor_token(client: TestClient, db: Session):
    """PR #932 CodeRabbit finding: an identify that read the source guest before an email
    merge can arrive after the merge response. The stale source token must resolve to the
    survivor and be replaced by the survivor's token, not re-issued."""
    merged = _merge_two_devices(client, db, "race@test.com")
    client.cookies.clear()
    client.cookies.set("wrzdj_guest", merged["stale_token"])

    resp = client.post("/api/public/guest/identify", json={"fingerprint_hash": "race_stale_fp"})

    assert resp.status_code == 200
    assert resp.json()["action"] == "cookie_hit"
    assert resp.json()["guest_id"] == merged["survivor"]["guest_id"]
    survivor = db.get(Guest, merged["survivor"]["guest_id"])
    assert resp.cookies["wrzdj_guest"] == survivor.token
    assert resp.cookies["wrzdj_guest"] != merged["stale_token"]


def test_identify_with_expired_tombstone_cookie_is_treated_as_cookieless(
    client: TestClient, db: Session
):
    """#932: a merged-away token forwards only for the cookie's own lifetime. Past that it
    is dead, and identify must not hand out the survivor's token for it."""
    from app.core.config import get_settings

    merged = _merge_two_devices(client, db, "expired@test.com")
    tomb = db.query(Guest).filter(Guest.token == merged["stale_token"]).one()
    tomb.merged_at = utcnow() - timedelta(seconds=get_settings().guest_cookie_max_age_seconds + 60)
    db.commit()
    survivor = db.get(Guest, merged["survivor"]["guest_id"])

    client.cookies.clear()
    client.cookies.set("wrzdj_guest", merged["stale_token"])
    resp = client.post("/api/public/guest/identify", json={"fingerprint_hash": "expired_fp"})

    assert resp.status_code == 200
    assert resp.json()["action"] != "cookie_hit"
    assert resp.json()["guest_id"] != survivor.id
    assert resp.cookies["wrzdj_guest"] != survivor.token
