"""Song request endpoint tests grouped by behavior."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request
from app.models.user import User
from app.services.auth import get_password_hash


class TestListRequests:
    """Tests for GET /api/events/{code}/requests endpoint."""

    def test_list_requests_success(
        self, client: TestClient, auth_headers: dict, test_event: Event, test_request: Request
    ):
        """Test listing requests for an event."""
        response = client.get(
            f"/api/events/{test_event.code}/requests",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["requests"]) == 1
        assert data["requests"][0]["id"] == test_request.id

    def test_list_requests_filter_by_status(
        self, client: TestClient, auth_headers: dict, test_event: Event, test_request: Request
    ):
        """Test filtering requests by status."""
        response = client.get(
            f"/api/events/{test_event.code}/requests?status=new",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["requests"]) == 1

        response = client.get(
            f"/api/events/{test_event.code}/requests?status=played",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_list_requests_no_auth(self, client: TestClient, test_event: Event):
        """Test listing requests without auth fails."""
        response = client.get(f"/api/events/{test_event.code}/requests")
        assert response.status_code == 401


class TestUpdateRequestStatus:
    """Tests for PATCH /api/requests/{id} endpoint."""

    def test_update_status_to_accepted(
        self, client: TestClient, auth_headers: dict, test_request: Request
    ):
        """Test accepting a request."""
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

    def test_update_status_to_playing(
        self, client: TestClient, auth_headers: dict, test_request: Request, db: Session
    ):
        """Test setting a request to playing updates now_playing."""
        # First accept it
        client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        # Then set to playing
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "playing"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "playing"

    def test_update_status_to_played(
        self, client: TestClient, auth_headers: dict, test_request: Request
    ):
        """Test marking a request as played (via valid transition path)."""
        # Must follow valid path: NEW -> ACCEPTED -> PLAYING -> PLAYED
        client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "playing"},
            headers=auth_headers,
        )
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "played"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "played"

    def test_update_status_to_rejected(
        self, client: TestClient, auth_headers: dict, test_request: Request
    ):
        """Test rejecting a request."""
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "rejected"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    def test_update_status_no_auth(self, client: TestClient, test_request: Request):
        """Test updating status without auth fails."""
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "accepted"},
        )
        assert response.status_code == 401

    def test_update_status_not_found(self, client: TestClient, auth_headers: dict):
        """Test updating nonexistent request."""
        response = client.patch(
            "/api/requests/99999",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        assert response.status_code == 404


class TestStatusStateMachine:
    """Tests for request status transition validation."""

    def test_invalid_new_to_played(
        self, client: TestClient, auth_headers: dict, test_request: Request, db: Session
    ):
        """NEW -> PLAYED is not a valid transition."""
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "played"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "Cannot transition" in response.json()["detail"]
        db.refresh(test_request)
        assert test_request.status == "new"

    def test_invalid_new_to_playing(
        self, client: TestClient, auth_headers: dict, test_request: Request, db: Session
    ):
        """NEW -> PLAYING is not a valid transition."""
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "playing"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        db.refresh(test_request)
        assert test_request.status == "new"

    def test_invalid_played_to_any(
        self, client: TestClient, auth_headers: dict, test_request: Request, db: Session
    ):
        """PLAYED is a terminal state — no transitions allowed."""
        # Move to PLAYED via valid path
        client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "playing"},
            headers=auth_headers,
        )
        client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "played"},
            headers=auth_headers,
        )
        # Try to transition from PLAYED
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "new"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        db.refresh(test_request)
        assert test_request.status == "played"

    def test_rejected_to_new(self, client: TestClient, auth_headers: dict, test_request: Request):
        """REJECTED -> NEW is valid (re-queue)."""
        client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "rejected"},
            headers=auth_headers,
        )
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "new"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "new"

    def test_accepted_to_rejected(
        self, client: TestClient, auth_headers: dict, test_request: Request
    ):
        """ACCEPTED -> REJECTED is valid."""
        client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "rejected"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"


class TestDeleteRequest:
    """Tests for DELETE /api/requests/{id} endpoint."""

    def test_delete_request_success(
        self, client: TestClient, auth_headers: dict, test_request: Request
    ):
        """Test deleting a request."""
        response = client.delete(
            f"/api/requests/{test_request.id}",
            headers=auth_headers,
        )
        assert response.status_code == 204

        # Verify it's gone
        response = client.patch(
            f"/api/requests/{test_request.id}",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_delete_request_not_found(self, client: TestClient, auth_headers: dict):
        """Test deleting a nonexistent request."""
        response = client.delete(
            "/api/requests/99999",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_delete_request_unauthorized(
        self, client: TestClient, db: Session, test_request: Request
    ):
        """Test deleting another user's request returns 403."""
        other_user = User(
            username="otheruser",
            password_hash=get_password_hash("otherpassword123"),
            role="dj",
        )
        db.add(other_user)
        db.commit()

        login_resp = client.post(
            "/api/auth/login",
            data={"username": "otheruser", "password": "otherpassword123"},
        )
        other_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        response = client.delete(
            f"/api/requests/{test_request.id}",
            headers=other_headers,
        )
        assert response.status_code == 403

    def test_delete_request_no_auth(self, client: TestClient, test_request: Request):
        """Test deleting without auth fails."""
        response = client.delete(f"/api/requests/{test_request.id}")
        assert response.status_code == 401
