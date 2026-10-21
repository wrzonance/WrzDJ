"""Scenario tests simulating real event conditions.

These tests verify the system solves the actual problems:
guests behind shared NAT, network switching, and abuse prevention.
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest

_CHROME_UA = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"


def _identify(client: TestClient, fingerprint: str, cookie: str | None = None) -> dict:
    """Helper: call /identify and return {guest_id, cookie}."""
    if cookie:
        client.cookies.set("wrzdj_guest", cookie)
    else:
        client.cookies.clear()

    resp = client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": fingerprint, "fingerprint_components": {}},
        headers={"User-Agent": _CHROME_UA},
    )
    assert resp.status_code == 200
    return {
        "guest_id": resp.json()["guest_id"],
        "cookie": resp.cookies.get("wrzdj_guest"),
    }


# --- NAT Scenario ---


def test_three_guests_same_ip_different_fingerprints(
    client: TestClient, db: Session, test_event: Event
):
    """3 phones on same WiFi. Each has unique fingerprint.
    All should get separate guest identities."""
    guest_a = _identify(client, "phone_a_fingerprint")
    guest_b = _identify(client, "phone_b_fingerprint")
    guest_c = _identify(client, "phone_c_fingerprint")

    ids = {guest_a["guest_id"], guest_b["guest_id"], guest_c["guest_id"]}
    assert len(ids) == 3, "All three guests should have unique IDs"


def test_two_identical_devices_separate_via_cookies(db: Session, test_event: Event):
    """Two school iPads with identical fingerprints.
    Each gets their own Guest record via direct DB creation (simulating
    simultaneous first visits), then stays separate via cookies."""
    from app.core.time import utcnow
    from app.models.guest import Guest

    now = utcnow()
    guest_a = Guest(
        token="ipad_a_" + "0" * 57,
        fingerprint_hash="identical_ipad_fp",
        user_agent="Mozilla/5.0 (iPad; CPU OS 17_4) Version/17.4 Safari/604.1",
        created_at=now,
        last_seen_at=now,
    )
    guest_b = Guest(
        token="ipad_b_" + "0" * 57,
        fingerprint_hash="identical_ipad_fp",
        user_agent="Mozilla/5.0 (iPad; CPU OS 17_4) Version/17.4 Safari/604.1",
        created_at=now,
        last_seen_at=now,
    )
    db.add_all([guest_a, guest_b])
    db.commit()
    db.refresh(guest_a)
    db.refresh(guest_b)

    assert guest_a.id != guest_b.id

    from app.services.guests.identity import identify_guest

    result_a = identify_guest(
        db,
        token_from_cookie=guest_a.token,
        fingerprint_hash="identical_ipad_fp",
        user_agent="Mozilla/5.0 (iPad; CPU OS 17_4) Version/17.4 Safari/604.1",
    )
    result_b = identify_guest(
        db,
        token_from_cookie=guest_b.token,
        fingerprint_hash="identical_ipad_fp",
        user_agent="Mozilla/5.0 (iPad; CPU OS 17_4) Version/17.4 Safari/604.1",
    )
    assert result_a.guest_id == guest_a.id
    assert result_b.guest_id == guest_b.id
    assert result_a.guest_id != result_b.guest_id


# --- Network Switch Scenario ---


def test_guest_returns_with_cookie_different_ip(client: TestClient, db: Session, test_event: Event):
    """Guest identifies on WiFi, returns on cellular.
    Cookie persists -> same guest_id."""
    first = _identify(client, "stable_device_fp")
    cookie = first["cookie"]

    second = _identify(client, "stable_device_fp", cookie=cookie)
    assert second["guest_id"] == first["guest_id"]


def test_guest_clears_cookies_returns_same_device(
    client: TestClient, db: Session, test_event: Event
):
    """Guest clears cookies, returns days later (cross-event scenario). Fingerprint
    reconciliation recovers identity once the quiet period has elapsed. New cookie issued."""
    first = _identify(client, "persistent_device_fp")
    original_id = first["guest_id"]

    # Simulate the guest returning after >12 hours (e.g., next event)
    g = db.query(Guest).filter(Guest.id == original_id).one()
    g.last_seen_at = utcnow() - timedelta(hours=13)
    db.commit()

    second = _identify(client, "persistent_device_fp", cookie=None)
    assert second["guest_id"] == original_id
    assert second["cookie"] is not None


# --- Abuse Scenario ---


def test_incognito_does_not_reset_identity(client: TestClient, db: Session, test_event: Event):
    """Guest identified, opens incognito hours later (no cookie, same fingerprint).
    Reconciliation re-links to same guest once the quiet period has elapsed."""
    normal = _identify(client, "troublemaker_fp")
    original_id = normal["guest_id"]

    # Backdate so the guest is outside the 12-hour concurrent-activity window
    g = db.query(Guest).filter(Guest.id == original_id).one()
    g.last_seen_at = utcnow() - timedelta(hours=13)
    db.commit()

    incognito = _identify(client, "troublemaker_fp", cookie=None)
    assert incognito["guest_id"] == original_id
