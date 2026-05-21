"""Assert that guest identity is resolved by guest_id (cookie + ThumbmarkJS) only.

These tests reproduce the original 'wrzonance' production bug where two
guests behind a shared NAT inherited each other's nicknames via the IP
fallback in collect_service.get_profile(). They FAIL on the pre-cleanup
codebase and PASS after the cleanup is complete.

See: docs/RECOVERY-IP-IDENTITY.md
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.request import Request as SongRequest
from app.models.request import RequestStatus
from app.services import collect as collect_service
from app.services.vote import add_vote


def _enable_collection(db: Session, event: Event) -> None:
    now = utcnow()
    event.collection_opens_at = now - timedelta(hours=1)
    event.live_starts_at = now + timedelta(hours=1)
    db.commit()
    db.refresh(event)


def _make_guest(db: Session, suffix: str) -> Guest:
    """Build a fully gate-clearing guest (verified email + human cookie issued by _set_cookie)."""
    import hashlib

    email = f"{suffix}@example.com"
    g = Guest(
        token=suffix.ljust(64, "0"),
        fingerprint_hash=f"fp_{suffix}",
        verified_email=email,
        email_hash=hashlib.sha256(email.encode()).hexdigest(),
        email_verified_at=utcnow(),
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


def _set_cookie(client: TestClient, guest: Guest) -> None:
    from fastapi import Response

    from app.services.human_verification import COOKIE_NAME as HUMAN_COOKIE_NAME
    from app.services.human_verification import issue_human_cookie

    resp = Response()
    issue_human_cookie(resp, guest.id)
    raw = resp.headers.get("set-cookie", "")
    human_value = raw.split("=", 1)[1].split(";", 1)[0] if "=" in raw else ""

    client.cookies.clear()
    client.cookies.set("wrzdj_guest", guest.token)
    if human_value:
        client.cookies.set(HUMAN_COOKIE_NAME, human_value)


def test_get_profile_returns_none_without_guest_id(db: Session, test_event: Event):
    """get_profile(guest_id=None) must return None — no IP fallback, no nickname leak."""
    result = collect_service.get_profile(db, event_id=test_event.id, guest_id=None)
    assert result is None


def test_two_guests_same_ip_get_distinct_profiles(
    client: TestClient, db: Session, test_event: Event
):
    """The original bug: guest A sets nickname, guest B (different cookie, same IP) must
    NOT inherit guest A's nickname."""
    _enable_collection(db, test_event)

    guest_a = _make_guest(db, "a")
    _set_cookie(client, guest_a)
    r = client.post(
        f"/api/public/collect/{test_event.code}/profile",
        json={"nickname": "alpha"},
    )
    assert r.status_code == 200
    assert r.json()["nickname"] == "alpha"

    guest_b = _make_guest(db, "b")
    _set_cookie(client, guest_b)
    r = client.get(f"/api/public/collect/{test_event.code}/profile")
    assert r.status_code == 200
    assert r.json()["nickname"] is None, (
        "Guest B must NOT inherit Guest A's nickname via IP fallback — "
        "see docs/RECOVERY-IP-IDENTITY.md"
    )


def test_my_picks_empty_without_guest_id(client: TestClient, db: Session, test_event: Event):
    """An anonymous request (no cookie) must see no my-picks rows even when
    other guests have submitted from the 'same IP' (TestClient default host)."""
    _enable_collection(db, test_event)

    guest_a = _make_guest(db, "a")
    _set_cookie(client, guest_a)
    client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={
            "song_title": "Test Song",
            "artist": "Test Artist",
            "source": "manual",
        },
    )

    client.cookies.clear()
    r = client.get(f"/api/public/collect/{test_event.code}/profile/me")
    # /profile/me is now hard-gated (require_email_verified). Anonymous calls
    # 403 instead of returning empty — stricter than the prior empty fallback,
    # which is the desired behavior post-2026-05-20 collection hardening.
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "human_verification_required"


def test_has_requested_false_without_guest_id(client: TestClient, db: Session, test_event: Event):
    """Anonymous /has-requested must not match by IP."""
    _enable_collection(db, test_event)

    guest_a = _make_guest(db, "a")
    db.add(
        SongRequest(
            event_id=test_event.id,
            song_title="X",
            artist="Y",
            source="manual",
            status=RequestStatus.NEW.value,
            dedupe_key="dk_x",
            guest_id=guest_a.id,
        )
    )
    db.commit()

    client.cookies.clear()
    r = client.get(f"/api/public/events/{test_event.join_code}/has-requested")
    assert r.status_code == 200
    assert r.json()["has_requested"] is False


def test_collect_submit_ownership_check_uses_guest_id_only(
    client: TestClient, db: Session, test_event: Event
):
    """Guest A submits; guest B (different cookie, same TestClient IP) submits same song.
    Must NOT receive 409 'You already picked this one!' — IP must not match owner."""
    _enable_collection(db, test_event)

    guest_a = _make_guest(db, "a")
    _set_cookie(client, guest_a)
    r = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "Anthem", "artist": "ArtistA", "source": "manual"},
    )
    assert r.status_code in (200, 201)

    guest_b = _make_guest(db, "b")
    _set_cookie(client, guest_b)
    r = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "Anthem", "artist": "ArtistA", "source": "manual"},
    )
    assert r.status_code != 409, (
        "Guest B must not be flagged as the owner of guest A's submission via IP — "
        f"got {r.status_code}: {r.json()}"
    )


def test_collect_vote_ownership_check_uses_guest_id_only(
    client: TestClient, db: Session, test_event: Event
):
    """Guest A submits, guest B votes on it (different cookie, same TestClient IP).
    Must NOT receive 409 'Can't vote on your own pick' — IP must not establish ownership."""
    _enable_collection(db, test_event)

    guest_a = _make_guest(db, "a")
    _set_cookie(client, guest_a)
    r = client.post(
        f"/api/public/collect/{test_event.code}/requests",
        json={"song_title": "Banger", "artist": "ArtistA", "source": "manual"},
    )
    request_id = r.json()["id"]

    guest_b = _make_guest(db, "b")
    _set_cookie(client, guest_b)
    r = client.post(
        f"/api/public/collect/{test_event.code}/vote",
        json={"request_id": request_id},
    )
    assert r.status_code != 409, (
        f"Guest B must not be blocked as 'own pick' — got {r.status_code}: {r.json()}"
    )


def test_vote_dedup_by_guest_id_only(db: Session, test_request: SongRequest):
    """Two guests can vote on the same request — IP-based dedup must not coalesce them."""
    guest_a = _make_guest(db, "a")
    guest_b = _make_guest(db, "b")

    add_vote(db, test_request.id, guest_id=guest_a.id)
    _, is_new = add_vote(db, test_request.id, guest_id=guest_b.id)
    assert is_new is True

    db.refresh(test_request)
    assert test_request.vote_count == 2
