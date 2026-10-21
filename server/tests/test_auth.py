"""Tests for authentication endpoints."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.models.user import User
from app.services.auth import create_access_token, decode_token


def test_token_operations_read_current_settings():
    first_secret = "first-test-secret-for-settings-rotation" + "a" * 16
    rotated_secret = "rotated-test-secret-for-settings-rotation" + "b" * 16
    assert len(first_secret.encode()) >= 32
    assert len(rotated_secret.encode()) >= 32

    with patch(
        "app.services.auth.get_settings",
        return_value=SimpleNamespace(jwt_secret=first_secret, jwt_expire_minutes=60),
    ):
        token = create_access_token({"sub": "dj", "tv": 1}, timedelta(minutes=5))

    with patch(
        "app.services.auth.get_settings",
        return_value=SimpleNamespace(jwt_secret=rotated_secret, jwt_expire_minutes=60),
    ):
        assert decode_token(token) is None


class TestLogin:
    """Tests for /api/auth/login endpoint."""

    def test_login_success(self, client: TestClient, test_user: User):
        """Test successful login returns access token."""
        response = client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "testpassword123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client: TestClient, test_user: User):
        """Test login with wrong password fails."""
        response = client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "wrongpassword"},
        )
        assert response.status_code == 401
        # Error message should be generic (prevent user enumeration)
        detail = response.json()["detail"].lower()
        assert "password" in detail or "incorrect" in detail

    def test_login_nonexistent_user(self, client: TestClient):
        """Test login with nonexistent user fails."""
        response = client.post(
            "/api/auth/login",
            data={"username": "nonexistent", "password": "testpassword123"},
        )
        assert response.status_code == 401
        # Error message should be same as wrong password (prevent user enumeration)
        detail = response.json()["detail"].lower()
        assert "password" in detail or "incorrect" in detail

    def test_login_empty_username(self, client: TestClient):
        """Test login with empty username fails."""
        response = client.post(
            "/api/auth/login",
            data={"username": "", "password": "testpassword123"},
        )
        assert response.status_code == 422 or response.status_code == 401

    def test_login_empty_password(self, client: TestClient, test_user: User):
        """Test login with empty password fails."""
        response = client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": ""},
        )
        assert response.status_code == 422 or response.status_code == 401


class TestAuthMe:
    """Tests for /api/auth/me endpoint."""

    def test_me_authenticated(self, client: TestClient, auth_headers: dict):
        """Test /me returns user info when authenticated."""
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert "id" in data

    def test_me_no_token(self, client: TestClient):
        """Test /me rejects requests without token."""
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    def test_me_invalid_token(self, client: TestClient):
        """Test /me rejects requests with invalid token."""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalidtoken"},
        )
        assert response.status_code == 401

    def test_me_malformed_auth_header(self, client: TestClient):
        """Test /me rejects malformed Authorization header."""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "NotBearer token"},
        )
        assert response.status_code == 401

    def test_me_returns_help_pages_seen(self, client: TestClient, auth_headers: dict):
        """Test /me includes help_pages_seen as empty array by default."""
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["help_pages_seen"] == []


class TestHelpPageSeen:
    """Tests for /api/auth/help-seen endpoint."""

    def test_mark_help_page_seen(self, client: TestClient, auth_headers: dict):
        """Test marking a help page as seen returns 200."""
        response = client.post(
            "/api/auth/help-seen",
            json={"page": "admin-overview"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_mark_help_page_seen_persists(self, client: TestClient, auth_headers: dict):
        """Test marked page appears in /me response."""
        client.post(
            "/api/auth/help-seen",
            json={"page": "admin-overview"},
            headers=auth_headers,
        )
        response = client.get("/api/auth/me", headers=auth_headers)
        assert "admin-overview" in response.json()["help_pages_seen"]

    def test_mark_help_page_seen_idempotent(self, client: TestClient, auth_headers: dict):
        """Test marking same page twice doesn't duplicate."""
        client.post(
            "/api/auth/help-seen",
            json={"page": "events"},
            headers=auth_headers,
        )
        client.post(
            "/api/auth/help-seen",
            json={"page": "events"},
            headers=auth_headers,
        )
        response = client.get("/api/auth/me", headers=auth_headers)
        pages = response.json()["help_pages_seen"]
        assert pages.count("events") == 1

    def test_mark_help_page_seen_invalid(self, client: TestClient, auth_headers: dict):
        """Test invalid page ID returns 422."""
        response = client.post(
            "/api/auth/help-seen",
            json={"page": "INVALID PAGE!"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_mark_help_page_seen_no_auth(self, client: TestClient):
        """Test endpoint requires authentication."""
        response = client.post(
            "/api/auth/help-seen",
            json={"page": "admin-overview"},
        )
        assert response.status_code == 401
