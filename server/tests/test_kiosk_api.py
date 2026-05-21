"""Tests for kiosk API endpoints."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.user import User
from app.services.kiosk import complete_pairing, create_kiosk


class TestKioskPairing:
    """POST /api/public/kiosk/pair"""

    def test_creates_pairing_session(self, client: TestClient):
        challenge = client.get("/api/public/kiosk/pair-challenge").json()
        resp = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": challenge["nonce"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["pair_code"]) == 6
        assert len(data["session_token"]) == 64
        assert "expires_at" in data

    def test_pair_code_is_alphanumeric(self, client: TestClient):
        challenge = client.get("/api/public/kiosk/pair-challenge").json()
        resp = client.post(
            "/api/public/kiosk/pair",
            headers={"X-Pair-Nonce": challenge["nonce"]},
        )
        code = resp.json()["pair_code"]
        assert code.isalnum()
        assert code == code.upper()


class TestKioskPairStatus:
    """GET /api/public/kiosk/pair/{pair_code}/status"""

    def test_returns_pairing_status(self, client: TestClient, db: Session):
        kiosk = create_kiosk(db)
        resp = client.get(f"/api/public/kiosk/pair/{kiosk.pair_code}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pairing"
        assert resp.json()["event_code"] is None

    def test_returns_active_status_with_event(
        self, client: TestClient, db: Session, test_user: User, test_event: Event
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.get(f"/api/public/kiosk/pair/{kiosk.pair_code}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["event_code"] == test_event.code
        assert data["event_name"] == test_event.name

    def test_returns_expired_status(self, client: TestClient, db: Session):
        kiosk = create_kiosk(db)
        kiosk.pair_expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        resp = client.get(f"/api/public/kiosk/pair/{kiosk.pair_code}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "expired"

    def test_404_for_unknown_code(self, client: TestClient):
        resp = client.get("/api/public/kiosk/pair/ZZZZZZ/status")
        assert resp.status_code == 404


class TestKioskSessionAssignment:
    """GET /api/public/kiosk/session/assignment (token in X-Kiosk-Session header)"""

    def test_returns_event_info(
        self, client: TestClient, db: Session, test_user: User, test_event: Event
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.get(
            "/api/public/kiosk/session/assignment",
            headers={"X-Kiosk-Session": kiosk.session_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["event_code"] == test_event.code
        assert data["event_name"] == test_event.name

    def test_updates_last_seen(
        self, client: TestClient, db: Session, test_user: User, test_event: Event
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        assert kiosk.last_seen_at is None
        client.get(
            "/api/public/kiosk/session/assignment",
            headers={"X-Kiosk-Session": kiosk.session_token},
        )
        db.refresh(kiosk)
        assert kiosk.last_seen_at is not None

    def test_401_missing_header(self, client: TestClient):
        resp = client.get("/api/public/kiosk/session/assignment")
        assert resp.status_code == 401

    def test_404_for_unknown_token(self, client: TestClient):
        resp = client.get(
            "/api/public/kiosk/session/assignment",
            headers={"X-Kiosk-Session": "x" * 64},
        )
        assert resp.status_code == 404

    def test_returns_pairing_status_before_paired(self, client: TestClient, db: Session):
        kiosk = create_kiosk(db)
        resp = client.get(
            "/api/public/kiosk/session/assignment",
            headers={"X-Kiosk-Session": kiosk.session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pairing"
        assert resp.json()["event_code"] is None

    def test_returns_expired_for_pairing_kiosk_past_ttl(self, client: TestClient, db: Session):
        kiosk = create_kiosk(db)
        kiosk.pair_expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        resp = client.get(
            "/api/public/kiosk/session/assignment",
            headers={"X-Kiosk-Session": kiosk.session_token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "expired"
        assert resp.json()["event_code"] is None

    def test_old_url_path_endpoint_removed(self, client: TestClient, db: Session):
        """Verify the old path-token endpoint no longer exists."""
        kiosk = create_kiosk(db)
        resp = client.get(f"/api/public/kiosk/session/{kiosk.session_token}/assignment")
        assert resp.status_code == 404 or resp.status_code == 405


class TestCompletePairingEndpoint:
    """POST /api/kiosk/pair/{pair_code}/complete"""

    def test_success(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        resp = client.post(
            f"/api/kiosk/pair/{kiosk.pair_code}/complete",
            json={"event_code": test_event.code},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["event_code"] == test_event.code

    def test_401_no_auth(self, client: TestClient, db: Session, test_event: Event):
        kiosk = create_kiosk(db)
        resp = client.post(
            f"/api/kiosk/pair/{kiosk.pair_code}/complete",
            json={"event_code": test_event.code},
        )
        assert resp.status_code == 401

    def test_403_pending_user(
        self,
        client: TestClient,
        db: Session,
        pending_headers: dict,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        resp = client.post(
            f"/api/kiosk/pair/{kiosk.pair_code}/complete",
            json={"event_code": test_event.code},
            headers=pending_headers,
        )
        assert resp.status_code == 403

    def test_410_expired_code(
        self, client: TestClient, db: Session, auth_headers: dict, test_event: Event
    ):
        kiosk = create_kiosk(db)
        kiosk.pair_expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        resp = client.post(
            f"/api/kiosk/pair/{kiosk.pair_code}/complete",
            json={"event_code": test_event.code},
            headers=auth_headers,
        )
        assert resp.status_code == 410

    def test_409_already_paired(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.post(
            f"/api/kiosk/pair/{kiosk.pair_code}/complete",
            json={"event_code": test_event.code},
            headers=auth_headers,
        )
        assert resp.status_code == 409

    def test_404_invalid_pair_code(self, client: TestClient, auth_headers: dict, test_event: Event):
        resp = client.post(
            "/api/kiosk/pair/ZZZZZZ/complete",
            json={"event_code": test_event.code},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_404_invalid_event(self, client: TestClient, db: Session, auth_headers: dict):
        kiosk = create_kiosk(db)
        resp = client.post(
            f"/api/kiosk/pair/{kiosk.pair_code}/complete",
            json={"event_code": "NONEXIST"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestListMyKiosks:
    """GET /api/kiosk/mine"""

    def test_returns_user_kiosks(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.get("/api/kiosk/mine", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == kiosk.id
        # session_token must NOT be included
        assert "session_token" not in data[0]

    def test_401_no_auth(self, client: TestClient):
        resp = client.get("/api/kiosk/mine")
        assert resp.status_code == 401

    def test_excludes_other_users_kiosks(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        admin_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, admin_user.id)
        resp = client.get("/api/kiosk/mine", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 0


class TestAssignKiosk:
    """PATCH /api/kiosk/{kiosk_id}/assign"""

    def test_changes_event(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        event2 = Event(
            code="EVT002",
            join_code="EVT002J",
            name="Second Event",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event2)
        db.commit()
        resp = client.patch(
            f"/api/kiosk/{kiosk.id}/assign",
            json={"event_code": "EVT002"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["event_code"] == "EVT002"

    def test_403_non_owner(
        self,
        client: TestClient,
        db: Session,
        admin_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.patch(
            f"/api/kiosk/{kiosk.id}/assign",
            json={"event_code": test_event.code},
            headers=admin_headers,
        )
        assert resp.status_code == 403

    def test_404_invalid_event(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.patch(
            f"/api/kiosk/{kiosk.id}/assign",
            json={"event_code": "NONEXIST"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestRenameKiosk:
    """PATCH /api/kiosk/{kiosk_id}"""

    def test_updates_name(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.patch(
            f"/api/kiosk/{kiosk.id}",
            json={"name": "Bar Kiosk"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Bar Kiosk"

    def test_403_non_owner(
        self,
        client: TestClient,
        db: Session,
        admin_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.patch(
            f"/api/kiosk/{kiosk.id}",
            json={"name": "Hacked"},
            headers=admin_headers,
        )
        assert resp.status_code == 403

    def test_422_name_too_long(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.patch(
            f"/api/kiosk/{kiosk.id}",
            json={"name": "x" * 101},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestDeleteKiosk:
    """DELETE /api/kiosk/{kiosk_id}"""

    def test_removes_kiosk(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.delete(f"/api/kiosk/{kiosk.id}", headers=auth_headers)
        assert resp.status_code == 204

    def test_403_non_owner(
        self,
        client: TestClient,
        db: Session,
        admin_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        resp = client.delete(f"/api/kiosk/{kiosk.id}", headers=admin_headers)
        assert resp.status_code == 403

    def test_404_nonexistent(self, client: TestClient, auth_headers: dict):
        resp = client.delete("/api/kiosk/99999", headers=auth_headers)
        assert resp.status_code == 404


class TestKioskIdor:
    """TDD guard for CRIT-3 and CRIT-4 — kiosk pairing/reassignment IDOR.

    Before the fix, any authenticated DJ could pair or reassign a kiosk
    to an event owned by another DJ, simply by knowing (or brute-forcing)
    the target event code. The fix enforces that the caller owns the
    target event (or is an admin).

    See docs/security/audit-2026-04-08.md CRIT-3 and CRIT-4.
    """

    @staticmethod
    def _make_victim_event(db: Session, owner: User, code: str = "VICTIM") -> Event:
        evt = Event(
            code=code,
            join_code=f"{code}J"[:10],
            name="Victim Event",
            created_by_user_id=owner.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(evt)
        db.commit()
        db.refresh(evt)
        return evt

    def test_complete_pairing_rejects_non_owned_event(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        admin_user: User,
    ):
        """CRIT-3: a DJ must not be able to pair a kiosk to someone else's event."""
        victim_event = self._make_victim_event(db, admin_user)
        kiosk = create_kiosk(db)

        resp = client.post(
            f"/api/kiosk/pair/{kiosk.pair_code}/complete",
            json={"event_code": victim_event.code},
            headers=auth_headers,  # test_user, NOT the victim (admin_user)
        )
        assert resp.status_code == 403
        # Kiosk must still be in 'pairing' state — not silently paired
        db.refresh(kiosk)
        assert kiosk.status == "pairing"
        assert kiosk.event_code is None

    def test_assign_kiosk_rejects_non_owned_event(
        self,
        client: TestClient,
        db: Session,
        auth_headers: dict,
        test_user: User,
        test_event: Event,
        admin_user: User,
    ):
        """CRIT-4: a DJ must not be able to reassign their own kiosk to someone else's event."""
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, test_event.code, test_user.id)
        victim_event = self._make_victim_event(db, admin_user)

        resp = client.patch(
            f"/api/kiosk/{kiosk.id}/assign",
            json={"event_code": victim_event.code},
            headers=auth_headers,
        )
        assert resp.status_code == 403
        # Kiosk still pointing at the original event
        db.refresh(kiosk)
        assert kiosk.event_code == test_event.code

    def test_admin_can_pair_kiosk_to_any_event(
        self,
        client: TestClient,
        db: Session,
        admin_headers: dict,
        test_user: User,
        test_event: Event,
    ):
        """Admin bypass must still work — admins can manage any event's kiosks."""
        kiosk = create_kiosk(db)
        resp = client.post(
            f"/api/kiosk/pair/{kiosk.pair_code}/complete",
            json={"event_code": test_event.code},  # owned by test_user, not admin
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["event_code"] == test_event.code

    def test_admin_can_reassign_any_kiosk_to_any_event(
        self,
        client: TestClient,
        db: Session,
        admin_headers: dict,
        admin_user: User,
        test_user: User,
        test_event: Event,
    ):
        """Admin bypass for reassignment."""
        # Admin owns a kiosk (paired by admin to their own event)
        admin_event = self._make_victim_event(db, admin_user, code="ADMIN1")
        kiosk = create_kiosk(db)
        complete_pairing(db, kiosk, admin_event.code, admin_user.id)

        # Admin reassigns their kiosk to test_user's event
        resp = client.patch(
            f"/api/kiosk/{kiosk.id}/assign",
            json={"event_code": test_event.code},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["event_code"] == test_event.code
