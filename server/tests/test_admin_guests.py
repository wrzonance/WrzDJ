"""Tests for the admin Guests endpoints and helpers (#862)."""

import hashlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.request import Request
from app.models.request_vote import RequestVote
from app.services.admin_guests import mask_email
from app.services.guests.identity import browser_label

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)

LIST_URL = "/api/admin/guests"


def _guest(db: Session, token: str, **fields) -> Guest:
    guest = Guest(token=token, **fields)
    db.add(guest)
    db.commit()
    db.refresh(guest)
    return guest


def _profile(db: Session, guest: Guest, event: Event, nickname: str | None) -> GuestProfile:
    profile = GuestProfile(event_id=event.id, guest_id=guest.id, nickname=nickname)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@pytest.fixture
def guests(db: Session, test_event: Event) -> dict[str, Guest]:
    """A: verified + 2 Turnstile passes + profile 'Alice'; B: shares A's hash, profile
    'bob_1'; C and D: no hash, no profile. A owns one request on test_event."""
    now = utcnow()
    a = _guest(
        db,
        "a" * 64,
        fingerprint_hash="h1",
        user_agent=IPHONE_UA,
        verified_email="alice@example.com",
        email_hash=hashlib.sha256(b"alice@example.com").hexdigest(),
        email_verified_at=now - timedelta(days=1),
        human_verified_at=now - timedelta(hours=2),
        human_verify_count=2,
        last_seen_at=now,
    )
    b = _guest(db, "b" * 64, fingerprint_hash="h1", last_seen_at=now - timedelta(hours=1))
    c = _guest(db, "c" * 64, last_seen_at=now - timedelta(hours=2))
    d = _guest(db, "d" * 64, last_seen_at=now - timedelta(hours=3))
    _profile(db, a, test_event, "Alice")
    _profile(db, b, test_event, "bob_1")
    db.add(
        Request(
            event_id=test_event.id,
            song_title="Song",
            artist="Artist",
            dedupe_key="dk_a",
            guest_id=a.id,
            nickname="Alice",
        )
    )
    db.commit()
    return {"a": a, "b": b, "c": c, "d": d}


def _items(client: TestClient, headers: dict, **params) -> dict:
    response = client.get(LIST_URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


class TestListGuests:
    def test_list_guests_shape(self, client, admin_headers, guests, test_event):
        data = _items(client, admin_headers)
        assert data["total"] == 4
        a = next(g for g in data["items"] if g["nickname"] == "Alice")
        assert a["email_verified"] is True
        assert a["email_masked"] == "a***@example.com"
        assert a["email_verified_at"]
        assert a["human_verify_count"] == 2
        assert a["human_verified_at"]
        assert a["fingerprint_short"] == "h1"
        assert a["fingerprint_shared_with"] == 1
        assert a["event_count"] == 1
        assert a["request_count"] == 1
        assert a["events"][0]["code"] == test_event.code
        assert a["events"][0]["nickname"] == "Alice"
        assert a["browser"] == "Safari · iOS"
        assert "verified_email" not in a

    def test_list_orders_by_last_seen_desc(self, client, admin_headers, guests):
        ids = [g["id"] for g in _items(client, admin_headers)["items"]]
        assert ids == [guests["a"].id, guests["b"].id, guests["c"].id, guests["d"].id]

    def test_unnamed_guest_has_null_nickname(self, client, admin_headers, guests):
        c = next(g for g in _items(client, admin_headers)["items"] if g["id"] == guests["c"].id)
        assert c["nickname"] is None
        assert c["email_verified"] is False
        assert c["email_masked"] is None
        assert c["human_verify_count"] == 0
        assert c["browser"] is None

    def test_filter_verified(self, client, admin_headers, guests):
        data = _items(client, admin_headers, filter="verified")
        assert data["total"] == 1
        assert data["items"][0]["id"] == guests["a"].id

    def test_filter_unverified(self, client, admin_headers, guests):
        assert _items(client, admin_headers, filter="unverified")["total"] == 3

    def test_filter_shared(self, client, admin_headers, guests):
        data = _items(client, admin_headers, filter="shared")
        assert {g["id"] for g in data["items"]} == {guests["a"].id, guests["b"].id}

    def test_null_fingerprints_are_not_shared(self, client, admin_headers, guests):
        data = _items(client, admin_headers)
        by_id = {g["id"]: g for g in data["items"]}
        assert by_id[guests["c"].id]["fingerprint_shared_with"] == 0
        assert by_id[guests["d"].id]["fingerprint_shared_with"] == 0
        assert by_id[guests["c"].id]["fingerprint_short"] is None

    def test_search_nickname_case_insensitive(self, client, admin_headers, guests):
        data = _items(client, admin_headers, q="ALICE")
        assert data["total"] == 1
        assert data["items"][0]["id"] == guests["a"].id

    def test_search_escapes_like_wildcards(self, client, admin_headers, guests):
        assert _items(client, admin_headers, q="b_b")["total"] == 0
        assert _items(client, admin_headers, q="%")["total"] == 0
        assert _items(client, admin_headers, q="b_1")["total"] == 1

    def test_pagination(self, client, admin_headers, guests):
        data = _items(client, admin_headers, page=2, limit=3)
        assert data["total"] == 4
        assert len(data["items"]) == 1
        assert data["page"] == 2

    def test_invalid_filter_400(self, client, admin_headers, guests):
        response = client.get(LIST_URL, headers=admin_headers, params={"filter": "x"})
        assert response.status_code == 400

    def test_dj_forbidden(self, client, auth_headers):
        assert client.get(LIST_URL, headers=auth_headers).status_code == 403

    def test_pending_forbidden(self, client, pending_headers):
        assert client.get(LIST_URL, headers=pending_headers).status_code == 403

    def test_anonymous_unauthorized(self, client):
        assert client.get(LIST_URL).status_code == 401


def _patch(client: TestClient, headers: dict, guest_id: int, body: dict):
    return client.patch(f"{LIST_URL}/{guest_id}", headers=headers, json=body)


def _patch_profile(client: TestClient, headers: dict, guest_id: int, event_id: int, body: dict):
    return client.patch(f"{LIST_URL}/{guest_id}/events/{event_id}", headers=headers, json=body)


class TestUpdateGuest:
    def test_patch_empty_body_is_noop(self, client, admin_headers, guests, db):
        response = _patch(client, admin_headers, guests["a"].id, {})
        assert response.status_code == 200
        assert response.json()["email_verified"] is True
        db.refresh(guests["a"])
        assert guests["a"].verified_email == "alice@example.com"

    def test_patch_revoke_email(self, client, admin_headers, guests, db):
        response = _patch(client, admin_headers, guests["a"].id, {"revoke_email": True})
        assert response.status_code == 200
        body = response.json()
        assert body["email_verified"] is False
        assert body["email_masked"] is None
        assert body["email_verified_at"] is None
        db.refresh(guests["a"])
        assert guests["a"].verified_email is None
        assert guests["a"].email_hash is None
        assert guests["a"].email_verified_at is None

    def test_patch_404(self, client, admin_headers):
        assert _patch(client, admin_headers, 999999, {"revoke_email": True}).status_code == 404

    def test_patch_dj_403(self, client, auth_headers, guests):
        assert _patch(client, auth_headers, guests["a"].id, {}).status_code == 403


class TestUpdateGuestProfile:
    def test_patch_profile_nickname(self, client, admin_headers, guests, test_event):
        response = _patch_profile(
            client, admin_headers, guests["a"].id, test_event.id, {"nickname": "  Zed "}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["nickname"] == "Zed"
        assert body["events"][0]["nickname"] == "Zed"

    def test_patch_profile_nickname_empty_clears(self, client, admin_headers, guests, test_event):
        response = _patch_profile(
            client, admin_headers, guests["a"].id, test_event.id, {"nickname": ""}
        )
        assert response.status_code == 200
        assert response.json()["events"][0]["nickname"] is None
        assert response.json()["nickname"] is None

    def test_patch_profile_nickname_conflict_409(self, client, admin_headers, guests, test_event):
        response = _patch_profile(
            client, admin_headers, guests["a"].id, test_event.id, {"nickname": "BOB_1"}
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "Nickname already taken in this event"

    def test_patch_profile_same_guest_case_change_ok(
        self, client, admin_headers, guests, test_event
    ):
        response = _patch_profile(
            client, admin_headers, guests["a"].id, test_event.id, {"nickname": "ALICE"}
        )
        assert response.status_code == 200
        assert response.json()["events"][0]["nickname"] == "ALICE"

    def test_patch_profile_404_when_not_member(self, client, admin_headers, guests, test_event):
        response = _patch_profile(
            client, admin_headers, guests["c"].id, test_event.id, {"nickname": "Zed"}
        )
        assert response.status_code == 404

    def test_patch_profile_404_unknown_guest(self, client, admin_headers, test_event):
        response = _patch_profile(client, admin_headers, 999999, test_event.id, {"nickname": "Z"})
        assert response.status_code == 404

    def test_patch_profile_dj_403(self, client, auth_headers, guests, test_event):
        response = _patch_profile(
            client, auth_headers, guests["a"].id, test_event.id, {"nickname": "Z"}
        )
        assert response.status_code == 403


class TestDeleteGuest:
    def test_delete_removes_profiles(self, client, admin_headers, guests, db):
        guest_id = guests["a"].id
        response = client.delete(f"{LIST_URL}/{guest_id}", headers=admin_headers)
        assert response.status_code == 204
        assert db.query(Guest).filter(Guest.id == guest_id).first() is None
        assert db.query(GuestProfile).filter(GuestProfile.guest_id == guest_id).count() == 0

    def test_delete_keeps_requests_anonymised(self, client, admin_headers, guests, db):
        guest_id = guests["a"].id
        request_row = db.query(Request).filter(Request.guest_id == guest_id).one()
        db.add(RequestVote(request_id=request_row.id, guest_id=guest_id))
        db.commit()
        request_id = request_row.id

        assert client.delete(f"{LIST_URL}/{guest_id}", headers=admin_headers).status_code == 204

        db.expire_all()
        kept = db.query(Request).filter(Request.id == request_id).one()
        assert kept.guest_id is None
        assert kept.nickname is None
        vote = db.query(RequestVote).filter(RequestVote.request_id == request_id).one()
        assert vote.guest_id is None

    def test_delete_404(self, client, admin_headers):
        assert client.delete(f"{LIST_URL}/999999", headers=admin_headers).status_code == 404

    def test_delete_dj_403(self, client, auth_headers, guests):
        response = client.delete(f"{LIST_URL}/{guests['a'].id}", headers=auth_headers)
        assert response.status_code == 403


class TestHelpers:
    def test_mask_email_keeps_first_char_and_domain(self):
        assert mask_email("alice@example.com") == "a***@example.com"
        assert mask_email("a@b.co") == "a***@b.co"

    def test_browser_label_known_ua(self):
        assert browser_label(IPHONE_UA) == "Safari · iOS"

    def test_browser_label_unknown_or_missing(self):
        assert browser_label("curl/8.0") is None
        assert browser_label(None) is None
