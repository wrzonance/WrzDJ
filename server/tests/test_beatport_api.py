"""Tests for Beatport API endpoints."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.user import User
from app.services.auth import get_password_hash


@pytest.fixture
def bp_api_user(db: Session) -> User:
    user = User(
        username="bp_api_user",
        password_hash=get_password_hash("testpassword123"),
        role="dj",
        beatport_access_token="bp_token_api",
        beatport_refresh_token="bp_refresh_api",
        beatport_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def bp_api_headers(client: TestClient, bp_api_user: User) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        data={"username": "bp_api_user", "password": "testpassword123"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def bp_api_event(db: Session, bp_api_user: User) -> Event:
    event = Event(
        code="BPAPI1",
        join_code="BPAPI1J",
        name="BP API Test Event",
        created_by_user_id=bp_api_user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


class TestBeatportStatus:
    def test_not_linked(self, client: TestClient, auth_headers: dict[str, str]):
        """User without Beatport tokens shows not linked."""
        response = client.get("/api/beatport/status", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["linked"] is False

    def test_linked(self, client: TestClient, bp_api_headers: dict[str, str]):
        """User with Beatport tokens shows linked."""
        response = client.get("/api/beatport/status", headers=bp_api_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["linked"] is True
        assert data["expires_at"] is not None

    def test_configured_field(self, client: TestClient, bp_api_headers: dict[str, str]):
        """Status includes configured field."""
        response = client.get("/api/beatport/status", headers=bp_api_headers)
        assert response.status_code == 200
        assert "configured" in response.json()

    def test_status_includes_subscription_field(
        self, client: TestClient, bp_api_headers: dict[str, str], bp_api_user: User, db: Session
    ):
        """Status includes subscription field from user model."""
        bp_api_user.beatport_subscription = "streaming"
        db.commit()

        response = client.get("/api/beatport/status", headers=bp_api_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["subscription"] == "streaming"

    def test_status_subscription_null_when_not_set(
        self, client: TestClient, bp_api_headers: dict[str, str]
    ):
        """Status subscription is null when user has no subscription stored."""
        response = client.get("/api/beatport/status", headers=bp_api_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["subscription"] is None

    def test_status_includes_integration_enabled(
        self, client: TestClient, bp_api_headers: dict[str, str]
    ):
        """Status includes integration_enabled flag."""
        response = client.get("/api/beatport/status", headers=bp_api_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["integration_enabled"] is True

    def test_status_disabled_when_admin_disables(
        self, client: TestClient, bp_api_headers: dict[str, str], admin_headers: dict
    ):
        """Status shows integration_enabled=false when admin disables Beatport."""
        client.patch(
            "/api/admin/integrations/beatport",
            headers=admin_headers,
            json={"enabled": False},
        )
        response = client.get("/api/beatport/status", headers=bp_api_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["integration_enabled"] is False


class TestBeatportLogin:
    def test_login_success(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Successful login links Beatport account."""
        with (
            patch("app.api.beatport.login_and_get_tokens") as mock_login,
            patch("app.api.beatport.settings") as mock_settings,
        ):
            mock_settings.beatport_client_id = "test-client-id"
            mock_login.return_value = {
                "access_token": "new-token",
                "refresh_token": "new-refresh",
                "expires_in": 600,
            }
            response = client.post(
                "/api/beatport/auth/login",
                json={"username": "dj_test", "password": "beatpass123"},
                headers=auth_headers,
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        mock_login.assert_called_once_with("dj_test", "beatpass123")

    def test_login_not_configured(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Login returns 503 when Beatport is not configured."""
        with patch("app.api.beatport.settings") as mock_settings:
            mock_settings.beatport_client_id = ""
            response = client.post(
                "/api/beatport/auth/login",
                json={"username": "user", "password": "pass"},
                headers=auth_headers,
            )
        assert response.status_code == 503

    def test_login_invalid_credentials(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Invalid credentials returns 401."""
        from unittest.mock import MagicMock

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 401

        with (
            patch("app.api.beatport.login_and_get_tokens") as mock_login,
            patch("app.api.beatport.settings") as mock_settings,
        ):
            mock_settings.beatport_client_id = "test-client-id"
            mock_login.side_effect = httpx.HTTPStatusError(
                "Unauthorized", request=MagicMock(), response=mock_response
            )
            response = client.post(
                "/api/beatport/auth/login",
                json={"username": "bad", "password": "creds"},
                headers=auth_headers,
            )
        assert response.status_code == 401

    def test_login_requires_auth(self, client: TestClient):
        """Login endpoint requires authentication."""
        response = client.post(
            "/api/beatport/auth/login",
            json={"username": "user", "password": "pass"},
        )
        assert response.status_code in (401, 403)

    def test_login_rejects_empty_username(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Login rejects empty username."""
        response = client.post(
            "/api/beatport/auth/login",
            json={"username": "", "password": "pass"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_login_rejects_empty_password(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Login rejects empty password."""
        response = client.post(
            "/api/beatport/auth/login",
            json={"username": "user", "password": ""},
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestBeatportDisconnect:
    def test_disconnect(self, client: TestClient, bp_api_headers: dict[str, str], db: Session):
        """Disconnect clears tokens."""
        response = client.post("/api/beatport/disconnect", headers=bp_api_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestBeatportEventSettings:
    def test_get_settings(
        self,
        client: TestClient,
        bp_api_headers: dict[str, str],
        bp_api_event: Event,
    ):
        response = client.get(
            f"/api/beatport/events/{bp_api_event.id}/settings",
            headers=bp_api_headers,
        )
        assert response.status_code == 200
        assert response.json()["beatport_sync_enabled"] is False

    def test_update_settings(
        self,
        client: TestClient,
        bp_api_headers: dict[str, str],
        bp_api_event: Event,
    ):
        response = client.put(
            f"/api/beatport/events/{bp_api_event.id}/settings",
            json={"beatport_sync_enabled": True},
            headers=bp_api_headers,
        )
        assert response.status_code == 200
        assert response.json()["beatport_sync_enabled"] is True

    def test_cannot_enable_without_token(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        test_event: Event,
    ):
        """Cannot enable sync without linked Beatport account."""
        response = client.put(
            f"/api/beatport/events/{test_event.id}/settings",
            json={"beatport_sync_enabled": True},
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_not_found(self, client: TestClient, bp_api_headers: dict[str, str]):
        response = client.get(
            "/api/beatport/events/99999/settings",
            headers=bp_api_headers,
        )
        assert response.status_code == 404


class TestBeatportSearch:
    def test_requires_auth(self, client: TestClient):
        """Search requires authentication."""
        response = client.get("/api/beatport/search?q=test")
        assert response.status_code in (401, 403)

    def test_requires_linked_account(self, client: TestClient, auth_headers: dict[str, str]):
        """Search requires linked Beatport account."""
        response = client.get(
            "/api/beatport/search?q=test",
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "not linked" in response.json()["detail"]

    def test_rejects_query_over_200_chars(self, client: TestClient, bp_api_headers: dict[str, str]):
        """Search rejects query longer than 200 characters."""
        long_query = "a" * 201
        response = client.get(
            f"/api/beatport/search?q={long_query}",
            headers=bp_api_headers,
        )
        assert response.status_code == 422

    def test_accepts_200_char_query(self, client: TestClient, bp_api_headers: dict[str, str]):
        """Search accepts query of exactly 200 characters (doesn't return 422)."""
        query_200 = "a" * 200
        response = client.get(
            f"/api/beatport/search?q={query_200}",
            headers=bp_api_headers,
        )
        # Should not be a validation error — may be 200 or other non-422 status
        assert response.status_code != 422
