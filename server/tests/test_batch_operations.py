"""Tests for batch operations (reject-all, bulk delete requests, bulk delete events)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.request_vote import RequestVote
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.event import bulk_delete_events
from app.services.request import bulk_delete_requests, reject_all_new_requests


def _create_request(db: Session, event: Event, title: str, status: str = "new") -> Request:
    """Helper to create a request with a unique dedupe key."""
    r = Request(
        event_id=event.id,
        song_title=title,
        artist="Artist",
        source="manual",
        status=status,
        dedupe_key=f"dedupe_{title}_{status}",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


class TestRejectAllNewRequests:
    """Tests for reject_all_new_requests service function."""

    def test_rejects_all_new(self, db: Session, test_event: Event):
        _create_request(db, test_event, "Song A", "new")
        _create_request(db, test_event, "Song B", "new")
        _create_request(db, test_event, "Song C", "accepted")

        count = reject_all_new_requests(db, test_event)
        assert count == 2

        remaining_new = (
            db.query(Request)
            .filter(Request.event_id == test_event.id, Request.status == "new")
            .count()
        )
        assert remaining_new == 0

    def test_does_not_reject_non_new(self, db: Session, test_event: Event):
        _create_request(db, test_event, "Accepted", "accepted")
        _create_request(db, test_event, "Rejected", "rejected")
        _create_request(db, test_event, "Playing", "playing")

        count = reject_all_new_requests(db, test_event)
        assert count == 0

    def test_returns_zero_for_empty_event(self, db: Session, test_event: Event):
        count = reject_all_new_requests(db, test_event)
        assert count == 0

    def test_sets_rejected_status(self, db: Session, test_event: Event):
        req = _create_request(db, test_event, "Song", "new")
        reject_all_new_requests(db, test_event)
        db.refresh(req)
        assert req.status == RequestStatus.REJECTED.value


class TestBulkDeleteRequests:
    """Tests for bulk_delete_requests service function."""

    def test_deletes_all_when_no_status_filter(self, db: Session, test_event: Event):
        _create_request(db, test_event, "A", "new")
        _create_request(db, test_event, "B", "accepted")
        _create_request(db, test_event, "C", "rejected")

        count = bulk_delete_requests(db, test_event)
        assert count == 3

        remaining = db.query(Request).filter(Request.event_id == test_event.id).count()
        assert remaining == 0

    def test_deletes_only_matching_status(self, db: Session, test_event: Event):
        _create_request(db, test_event, "A", "new")
        _create_request(db, test_event, "B", "rejected")
        _create_request(db, test_event, "C", "rejected")

        count = bulk_delete_requests(db, test_event, status="rejected")
        assert count == 2

        remaining = db.query(Request).filter(Request.event_id == test_event.id).count()
        assert remaining == 1

    def test_returns_zero_for_empty_event(self, db: Session, test_event: Event):
        count = bulk_delete_requests(db, test_event)
        assert count == 0

    def test_cascades_vote_deletion(self, db: Session, test_event: Event):
        req = _create_request(db, test_event, "Song", "new")
        vote = RequestVote(
            request_id=req.id,
        )
        db.add(vote)
        db.commit()

        count = bulk_delete_requests(db, test_event)
        assert count == 1
        assert db.query(RequestVote).count() == 0


class TestRejectAllEndpoint:
    """Tests for POST /api/events/{code}/requests/reject-all."""

    def test_reject_all_success(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        _create_request(db, test_event, "A", "new")
        _create_request(db, test_event, "B", "new")

        response = client.post(
            f"/api/events/{test_event.code}/requests/reject-all",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["count"] == 2

    def test_reject_all_returns_zero_when_none_new(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        _create_request(db, test_event, "Accepted", "accepted")

        response = client.post(
            f"/api/events/{test_event.code}/requests/reject-all",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_reject_all_requires_auth(self, client: TestClient, test_event: Event):
        response = client.post(
            f"/api/events/{test_event.code}/requests/reject-all",
        )
        assert response.status_code == 401

    def test_reject_all_requires_event_ownership(
        self, client: TestClient, test_event: Event, db: Session
    ):
        """Another DJ cannot reject requests on someone else's event."""
        other_user = User(
            username="otherdj",
            password_hash=get_password_hash("otherpassword123"),
            role="dj",
        )
        db.add(other_user)
        db.commit()

        login_resp = client.post(
            "/api/auth/login",
            data={"username": "otherdj", "password": "otherpassword123"},
        )
        assert login_resp.status_code == 200
        other_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        response = client.post(
            f"/api/events/{test_event.code}/requests/reject-all",
            headers=other_headers,
        )
        # get_owned_event returns 404 for non-owners (doesn't leak event existence)
        assert response.status_code == 404


class TestBulkDeleteEndpoint:
    """Tests for DELETE /api/events/{code}/requests/bulk."""

    def test_bulk_delete_all(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        _create_request(db, test_event, "A", "new")
        _create_request(db, test_event, "B", "rejected")

        response = client.delete(
            f"/api/events/{test_event.code}/requests/bulk",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["count"] == 2

    def test_bulk_delete_with_status_filter(
        self, client: TestClient, auth_headers: dict, test_event: Event, db: Session
    ):
        _create_request(db, test_event, "A", "new")
        _create_request(db, test_event, "B", "rejected")

        response = client.delete(
            f"/api/events/{test_event.code}/requests/bulk?status=rejected",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["count"] == 1

        remaining = db.query(Request).filter(Request.event_id == test_event.id).count()
        assert remaining == 1

    def test_bulk_delete_requires_auth(self, client: TestClient, test_event: Event):
        response = client.delete(
            f"/api/events/{test_event.code}/requests/bulk",
        )
        assert response.status_code == 401

    def test_bulk_delete_empty_returns_zero(
        self, client: TestClient, auth_headers: dict, test_event: Event
    ):
        response = client.delete(
            f"/api/events/{test_event.code}/requests/bulk",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["count"] == 0


def _derive_join_code(code: str) -> str:
    """Build a deterministic 6-char join_code that's guaranteed != code.

    Replaces the first character with a different letter so the result always
    differs from `code` while staying within the safe-alphabet length contract.
    """
    head = code[0].upper()
    swap = "Z" if head != "Z" else "Y"
    return (swap + code[1:])[:6].ljust(6, "X")[:6]


def _create_event(db: Session, user: User, code: str, name: str = "Test Event") -> Event:
    """Helper to create an event for bulk delete tests."""
    event = Event(
        code=code,
        join_code=_derive_join_code(code),
        name=name,
        created_by_user_id=user.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


class TestBulkDeleteEvents:
    """Tests for bulk_delete_events service function."""

    def test_bulk_delete_events_all_owned(self, db: Session, test_user: User):
        e1 = _create_event(db, test_user, "EVT01")
        e2 = _create_event(db, test_user, "EVT02")

        count = bulk_delete_events(db, ["EVT01", "EVT02"], user=test_user)
        assert count == 2

        remaining = db.query(Event).filter(Event.id.in_([e1.id, e2.id])).count()
        assert remaining == 0

    def test_bulk_delete_events_not_owned_fails(self, db: Session, test_user: User):
        other_user = User(
            username="otheruser",
            password_hash=get_password_hash("password123"),
            role="dj",
        )
        db.add(other_user)
        db.commit()

        _create_event(db, test_user, "EVT01")
        e_other = _create_event(db, other_user, "EVT02")

        try:
            bulk_delete_events(db, ["EVT01", "EVT02"], user=test_user)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not found" in str(e).lower() or "not owned" in str(e).lower()

        # Verify NONE were deleted (atomic)
        assert db.query(Event).filter(Event.code == "EVT01").count() == 1
        assert db.query(Event).filter(Event.id == e_other.id).count() == 1

    def test_bulk_delete_events_not_found_fails(self, db: Session, test_user: User):
        _create_event(db, test_user, "EVT01")

        try:
            bulk_delete_events(db, ["EVT01", "NONEXIST"], user=test_user)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

        # EVT01 should still exist (atomic)
        assert db.query(Event).filter(Event.code == "EVT01").count() == 1

    def test_bulk_delete_events_no_user_skips_ownership(self, db: Session, test_user: User):
        """Admin mode: user=None deletes any event regardless of owner."""
        other_user = User(
            username="otheruser2",
            password_hash=get_password_hash("password123"),
            role="dj",
        )
        db.add(other_user)
        db.commit()

        _create_event(db, test_user, "EVT01")
        _create_event(db, other_user, "EVT02")

        count = bulk_delete_events(db, ["EVT01", "EVT02"], user=None)
        assert count == 2

    def test_bulk_delete_events_cascades_children(self, db: Session, test_user: User):
        event = _create_event(db, test_user, "EVT01")
        req = Request(
            event_id=event.id,
            song_title="Song",
            artist="Artist",
            source="manual",
            status="new",
            dedupe_key="dedupe_cascade_test",
        )
        db.add(req)
        db.commit()
        db.refresh(req)
        req_id = req.id
        event_id = event.id

        vote = RequestVote(request_id=req_id)
        db.add(vote)
        db.commit()

        count = bulk_delete_events(db, ["EVT01"], user=test_user)
        assert count == 1
        assert db.query(Request).filter(Request.event_id == event_id).count() == 0
        assert db.query(RequestVote).filter(RequestVote.request_id == req_id).count() == 0

    def test_bulk_delete_events_empty_after_validation(self, db: Session, test_user: User):
        _create_event(db, test_user, "EVT01")
        _create_event(db, test_user, "EVT02")
        _create_event(db, test_user, "EVT03")

        count = bulk_delete_events(db, ["EVT01", "EVT02", "EVT03"], user=test_user)
        assert count == 3
        assert db.query(Event).filter(Event.created_by_user_id == test_user.id).count() == 0


class TestBulkDeleteEventsEndpoint:
    """Tests for POST /api/events/bulk-delete."""

    def test_bulk_delete_success(
        self, client: TestClient, auth_headers: dict, test_user: User, db: Session
    ):
        _create_event(db, test_user, "EVT01")
        _create_event(db, test_user, "EVT02")

        response = client.post(
            "/api/events/bulk-delete",
            headers=auth_headers,
            json={"codes": ["EVT01", "EVT02"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["count"] == 2

    def test_bulk_delete_not_owned(self, client: TestClient, auth_headers: dict, db: Session):
        other_user = User(
            username="otherdjuser",
            password_hash=get_password_hash("password123"),
            role="dj",
        )
        db.add(other_user)
        db.commit()
        _create_event(db, other_user, "OTHER1")

        response = client.post(
            "/api/events/bulk-delete",
            headers=auth_headers,
            json={"codes": ["OTHER1"]},
        )
        assert response.status_code == 404

    def test_bulk_delete_not_found(self, client: TestClient, auth_headers: dict):
        response = client.post(
            "/api/events/bulk-delete",
            headers=auth_headers,
            json={"codes": ["NONEXIST"]},
        )
        assert response.status_code == 404

    def test_bulk_delete_no_auth(self, client: TestClient):
        response = client.post(
            "/api/events/bulk-delete",
            json={"codes": ["EVT01"]},
        )
        assert response.status_code == 401

    def test_bulk_delete_empty_codes(self, client: TestClient, auth_headers: dict):
        response = client.post(
            "/api/events/bulk-delete",
            headers=auth_headers,
            json={"codes": []},
        )
        assert response.status_code == 422

    def test_bulk_delete_pending_user(self, client: TestClient, pending_headers: dict):
        response = client.post(
            "/api/events/bulk-delete",
            headers=pending_headers,
            json={"codes": ["EVT01"]},
        )
        assert response.status_code == 403


class TestAdminBulkDeleteEventsEndpoint:
    """Tests for POST /api/admin/events/bulk-delete."""

    def test_admin_bulk_delete_success(
        self, client: TestClient, admin_headers: dict, test_user: User, db: Session
    ):
        _create_event(db, test_user, "EVT01")
        _create_event(db, test_user, "EVT02")

        response = client.post(
            "/api/admin/events/bulk-delete",
            headers=admin_headers,
            json={"codes": ["EVT01", "EVT02"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["count"] == 2

    def test_admin_bulk_delete_not_found(self, client: TestClient, admin_headers: dict):
        response = client.post(
            "/api/admin/events/bulk-delete",
            headers=admin_headers,
            json={"codes": ["NONEXIST"]},
        )
        assert response.status_code == 404

    def test_admin_bulk_delete_no_auth(self, client: TestClient):
        response = client.post(
            "/api/admin/events/bulk-delete",
            json={"codes": ["EVT01"]},
        )
        assert response.status_code == 401

    def test_admin_bulk_delete_non_admin(self, client: TestClient, auth_headers: dict):
        response = client.post(
            "/api/admin/events/bulk-delete",
            headers=auth_headers,
            json={"codes": ["EVT01"]},
        )
        assert response.status_code == 403
