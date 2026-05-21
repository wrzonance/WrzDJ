"""Tests for admin API endpoints."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.user import User
from app.services.auth import get_password_hash


class TestAdminStats:
    def test_admin_gets_stats(self, client: TestClient, admin_headers: dict, db: Session):
        response = client.get("/api/admin/stats", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_users" in data
        assert "pending_users" in data
        assert "total_events" in data
        assert "total_requests" in data

    def test_dj_cannot_access_stats(self, client: TestClient, auth_headers: dict):
        response = client.get("/api/admin/stats", headers=auth_headers)
        assert response.status_code == 403

    def test_pending_cannot_access_stats(self, client: TestClient, pending_headers: dict):
        response = client.get("/api/admin/stats", headers=pending_headers)
        assert response.status_code == 403

    def test_unauthenticated_cannot_access_stats(self, client: TestClient):
        response = client.get("/api/admin/stats")
        assert response.status_code == 401


class TestAdminUserManagement:
    def test_list_users(self, client: TestClient, admin_headers: dict, db: Session):
        response = client.get("/api/admin/users", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 1

    def test_list_users_filter_by_role(self, client: TestClient, admin_headers: dict, test_user):
        response = client.get("/api/admin/users?role=dj", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        for user in data["items"]:
            assert user["role"] == "dj"

    def test_create_user(self, client: TestClient, admin_headers: dict):
        response = client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={"username": "newdjuser", "password": "newpassword123", "role": "dj"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newdjuser"
        assert data["role"] == "dj"

    def test_create_user_duplicate_username(
        self, client: TestClient, admin_headers: dict, test_user
    ):
        response = client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={"username": "testuser", "password": "newpassword123", "role": "dj"},
        )
        assert response.status_code == 409

    def test_create_user_invalid_role(self, client: TestClient, admin_headers: dict):
        response = client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={"username": "baduser", "password": "newpassword123", "role": "superuser"},
        )
        assert response.status_code == 400

    def test_update_user_role(self, client: TestClient, admin_headers: dict, test_user: User):
        response = client.patch(
            f"/api/admin/users/{test_user.id}",
            headers=admin_headers,
            json={"role": "admin"},
        )
        assert response.status_code == 200
        assert response.json()["role"] == "admin"

    def test_update_user_password(self, client: TestClient, admin_headers: dict, test_user: User):
        response = client.patch(
            f"/api/admin/users/{test_user.id}",
            headers=admin_headers,
            json={"password": "brandnewpassword123"},
        )
        assert response.status_code == 200

        # Verify new password works
        login_resp = client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "brandnewpassword123"},
        )
        assert login_resp.status_code == 200

    def test_deactivate_user(self, client: TestClient, admin_headers: dict, test_user: User):
        response = client.patch(
            f"/api/admin/users/{test_user.id}",
            headers=admin_headers,
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_update_nonexistent_user(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/users/99999",
            headers=admin_headers,
            json={"role": "dj"},
        )
        assert response.status_code == 404

    def test_last_admin_protection_demote(
        self, client: TestClient, admin_headers: dict, admin_user: User
    ):
        """Cannot demote the last admin."""
        response = client.patch(
            f"/api/admin/users/{admin_user.id}",
            headers=admin_headers,
            json={"role": "dj"},
        )
        assert response.status_code == 400
        assert "last admin" in response.json()["detail"].lower()

    def test_last_admin_protection_deactivate(
        self, client: TestClient, admin_headers: dict, admin_user: User
    ):
        """Cannot deactivate the last admin."""
        response = client.patch(
            f"/api/admin/users/{admin_user.id}",
            headers=admin_headers,
            json={"is_active": False},
        )
        assert response.status_code == 400
        assert "last admin" in response.json()["detail"].lower()

    def test_delete_user(self, client: TestClient, admin_headers: dict, test_user: User):
        response = client.delete(
            f"/api/admin/users/{test_user.id}",
            headers=admin_headers,
        )
        assert response.status_code == 204

    def test_self_deletion_prevention(
        self, client: TestClient, admin_headers: dict, admin_user: User
    ):
        """Admin cannot delete themselves."""
        response = client.delete(
            f"/api/admin/users/{admin_user.id}",
            headers=admin_headers,
        )
        assert response.status_code == 400
        assert "yourself" in response.json()["detail"].lower()

    def test_last_admin_protection_delete(
        self, client: TestClient, admin_headers: dict, admin_user: User
    ):
        """Cannot delete the last admin."""
        response = client.delete(
            f"/api/admin/users/{admin_user.id}",
            headers=admin_headers,
        )
        assert response.status_code == 400

    def test_delete_user_cascades_events(
        self, client: TestClient, admin_headers: dict, db: Session
    ):
        """Deleting a user should also delete their events."""
        user = User(
            username="doomeduser",
            password_hash=get_password_hash("password123"),
            role="dj",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        event = Event(
            code="DOOM01",
            join_code="EOOM01",
            name="Doomed Event",
            created_by_user_id=user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        db.add(event)
        db.commit()

        response = client.delete(
            f"/api/admin/users/{user.id}",
            headers=admin_headers,
        )
        assert response.status_code == 204

        # Event should be gone
        assert db.query(Event).filter(Event.code == "DOOM01").first() is None


class TestAdminEventManagement:
    def test_list_events(self, client: TestClient, admin_headers: dict, test_event):
        response = client.get("/api/admin/events", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert data["items"][0]["owner_username"] is not None

    def test_admin_edit_any_event(self, client: TestClient, admin_headers: dict, test_event):
        response = client.patch(
            f"/api/admin/events/{test_event.code}",
            headers=admin_headers,
            json={"name": "Updated by Admin"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated by Admin"

    def test_admin_delete_any_event(self, client: TestClient, admin_headers: dict, test_event):
        response = client.delete(
            f"/api/admin/events/{test_event.code}",
            headers=admin_headers,
        )
        assert response.status_code == 204

    def test_admin_delete_nonexistent_event(self, client: TestClient, admin_headers: dict):
        response = client.delete(
            "/api/admin/events/XXXXXX",
            headers=admin_headers,
        )
        assert response.status_code == 404


class TestAdminSettings:
    def test_get_settings(self, client: TestClient, admin_headers: dict):
        response = client.get("/api/admin/settings", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "registration_enabled" in data
        assert "search_rate_limit_per_minute" in data

    def test_update_settings_registration(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"registration_enabled": False},
        )
        assert response.status_code == 200
        assert response.json()["registration_enabled"] is False

    def test_update_settings_rate_limit(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"search_rate_limit_per_minute": 50},
        )
        assert response.status_code == 200
        assert response.json()["search_rate_limit_per_minute"] == 50

    def test_rate_limit_validation_min(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"search_rate_limit_per_minute": 0},
        )
        assert response.status_code == 422

    def test_rate_limit_validation_max(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"search_rate_limit_per_minute": 200},
        )
        assert response.status_code == 422

    def test_dj_cannot_update_settings(self, client: TestClient, auth_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=auth_headers,
            json={"registration_enabled": False},
        )
        assert response.status_code == 403


class TestPendingUserBlocking:
    def test_pending_user_can_access_me(self, client: TestClient, pending_headers: dict):
        response = client.get("/api/auth/me", headers=pending_headers)
        assert response.status_code == 200
        assert response.json()["role"] == "pending"

    def test_pending_user_cannot_create_event(self, client: TestClient, pending_headers: dict):
        response = client.post(
            "/api/events",
            headers=pending_headers,
            json={"name": "My Event"},
        )
        assert response.status_code == 403

    def test_pending_user_cannot_list_events(self, client: TestClient, pending_headers: dict):
        response = client.get("/api/events", headers=pending_headers)
        assert response.status_code == 403


class TestAdminLLMSettings:
    def test_get_settings_includes_llm_fields(self, client: TestClient, admin_headers: dict):
        response = client.get("/api/admin/settings", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "llm_enabled" in data
        assert "llm_model" in data
        assert "llm_rate_limit_per_minute" in data

    def test_update_llm_enabled(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"llm_enabled": False},
        )
        assert response.status_code == 200
        assert response.json()["llm_enabled"] is False

    def test_update_llm_model(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"llm_model": "claude-sonnet-4-5-20250929"},
        )
        assert response.status_code == 200
        assert response.json()["llm_model"] == "claude-sonnet-4-5-20250929"

    def test_update_llm_rate_limit(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"llm_rate_limit_per_minute": 10},
        )
        assert response.status_code == 200
        assert response.json()["llm_rate_limit_per_minute"] == 10

    def test_llm_rate_limit_validation_min(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"llm_rate_limit_per_minute": 0},
        )
        assert response.status_code == 422

    def test_llm_rate_limit_validation_max(self, client: TestClient, admin_headers: dict):
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"llm_rate_limit_per_minute": 31},
        )
        assert response.status_code == 422


class TestAdminHumanVerificationSettings:
    def test_get_settings_includes_human_verification_enforced(
        self, client: TestClient, admin_headers: dict
    ):
        response = client.get("/api/admin/settings", headers=admin_headers)
        assert response.status_code == 200
        assert "human_verification_enforced" in response.json()

    def test_admin_can_toggle_human_verification_enforced(
        self, client: TestClient, admin_headers: dict
    ):
        # Initially defaults to False
        response = client.get("/api/admin/settings", headers=admin_headers)
        assert response.json()["human_verification_enforced"] is False

        # Flip to True
        response = client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={"human_verification_enforced": True},
        )
        assert response.status_code == 200
        assert response.json()["human_verification_enforced"] is True

        # Verify persisted on subsequent GET
        response = client.get("/api/admin/settings", headers=admin_headers)
        assert response.json()["human_verification_enforced"] is True

    def test_dj_cannot_toggle_human_verification_enforced(
        self, client: TestClient, auth_headers: dict
    ):
        response = client.patch(
            "/api/admin/settings",
            headers=auth_headers,
            json={"human_verification_enforced": True},
        )
        assert response.status_code == 403


class TestAuthMeRole:
    def test_me_returns_role_for_admin(self, client: TestClient, admin_headers: dict):
        response = client.get("/api/auth/me", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["role"] == "admin"

    def test_me_returns_role_for_dj(self, client: TestClient, auth_headers: dict):
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["role"] == "dj"
