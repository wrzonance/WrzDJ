"""Song request endpoint tests grouped by behavior."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.user import User
from app.services.auth import get_password_hash


class TestRefreshMetadata:
    """Tests for POST /api/requests/{id}/refresh-metadata endpoint."""

    def test_refresh_metadata_success(
        self, client: TestClient, auth_headers: dict, test_request: Request, db: Session
    ):
        """Test refreshing metadata clears existing fields."""
        # Set some metadata first
        test_request.genre = "House"
        test_request.bpm = 128.0
        test_request.musical_key = "8A"
        db.commit()

        response = client.post(
            f"/api/requests/{test_request.id}/refresh-metadata",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Metadata should be cleared (re-enrichment happens in background)
        assert data["genre"] is None
        assert data["bpm"] is None
        assert data["musical_key"] is None

    def test_refresh_metadata_not_found(self, client: TestClient, auth_headers: dict):
        """Test refreshing metadata of a nonexistent request."""
        response = client.post(
            "/api/requests/99999/refresh-metadata",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_refresh_metadata_unauthorized(
        self, client: TestClient, db: Session, test_request: Request
    ):
        """Test refreshing another user's request returns 403."""
        other_user = User(
            username="otheruser2",
            password_hash=get_password_hash("otherpassword123"),
            role="dj",
        )
        db.add(other_user)
        db.commit()

        login_resp = client.post(
            "/api/auth/login",
            data={"username": "otheruser2", "password": "otherpassword123"},
        )
        other_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        response = client.post(
            f"/api/requests/{test_request.id}/refresh-metadata",
            headers=other_headers,
        )
        assert response.status_code == 403

    def test_refresh_metadata_no_auth(self, client: TestClient, test_request: Request):
        """Test refreshing without auth fails."""
        response = client.post(f"/api/requests/{test_request.id}/refresh-metadata")
        assert response.status_code == 401
