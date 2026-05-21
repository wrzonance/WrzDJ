"""F3 regression — two distinct cookie-identified guests behind the
same NAT IP must both be able to vote on the same request."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request as SongRequest
from app.models.request import RequestStatus
from app.models.user import User
from app.services.auth import get_password_hash


@pytest.fixture
def votable_event_and_request(db: Session) -> tuple[Event, SongRequest]:
    user = User(
        username="dj_f3",
        password_hash=get_password_hash("pw_f3_test_value"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    event = Event(
        code="F3VOTE",
        join_code="G3VOTE",
        name="NAT Vote Test",
        created_by_user_id=user.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    req = SongRequest(
        event_id=event.id,
        song_title="Shared Song",
        artist="Shared Artist",
        source="manual",
        status=RequestStatus.NEW.value,
        dedupe_key="f3_dedupe_key_voteme",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return event, req


def test_two_guests_one_nat_ip_both_vote(client, votable_event_and_request):
    """Both guests issue the SAME fingerprint to TestClient (which always
    reports IP='testclient'), but different cookie tokens via /identify."""
    event, req = votable_event_and_request

    # Guest A
    client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "fp_nat_guest_A", "fingerprint_components": {}},
    )
    vote_a = client.post(f"/api/requests/{req.id}/vote")
    assert vote_a.status_code == 200, vote_a.json()
    assert vote_a.json()["vote_count"] == 1
    assert vote_a.json()["status"] == "voted"

    # Switch identity, IP stays the same — Guest B
    client.cookies.clear()
    client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "fp_nat_guest_B_distinct", "fingerprint_components": {}},
    )
    vote_b = client.post(f"/api/requests/{req.id}/vote")
    assert vote_b.status_code == 200, vote_b.json()
    assert vote_b.json()["vote_count"] == 2, (
        "Two distinct cookie-identified guests on the same NAT IP must "
        "both successfully vote — F3 regression"
    )
    assert vote_b.json()["status"] == "voted"


def test_same_guest_double_vote_still_idempotent(client, votable_event_and_request):
    """Sanity: dropping the (req, fp) unique must not weaken the
    (req, guest_id) dedup. Same cookie voting twice = no-op second time."""
    _, req = votable_event_and_request

    client.post(
        "/api/public/guest/identify",
        json={"fingerprint_hash": "fp_idem_solo", "fingerprint_components": {}},
    )
    first = client.post(f"/api/requests/{req.id}/vote")
    assert first.status_code == 200
    assert first.json()["vote_count"] == 1
    assert first.json()["status"] == "voted"

    second = client.post(f"/api/requests/{req.id}/vote")
    assert second.status_code == 200
    assert second.json()["vote_count"] == 1
    assert second.json()["status"] == "already_voted"


def test_anon_vote_returns_401(client, votable_event_and_request):
    """No cookie -> 401. Identity-by-IP fallback removed; see docs/RECOVERY-IP-IDENTITY.md."""
    _, req = votable_event_and_request

    client.cookies.clear()
    resp = client.post(f"/api/requests/{req.id}/vote")
    assert resp.status_code == 401
