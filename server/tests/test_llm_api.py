"""Tests for the per-DJ LLM connector API + admin oversight API.

Exercises:
- CRUD endpoints, ownership scoping (404 for other DJs' connectors)
- policy gating (admin can disable connector types)
- credential rotation audit
- admin force-revoke + system default cleanup
- usage rollup
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.llm_connector import LlmAuditEvent, LlmConnector
from app.models.user import User
from app.services.auth import get_password_hash


# ---------- helpers ----------
def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.json()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make_other_dj(db: Session) -> User:
    user = User(
        username="otherdj",
        password_hash=get_password_hash("otherpassword123"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------- list / create / scope ----------
class TestPerDJConnectorsCRUD:
    def test_list_empty_for_new_user(self, client: TestClient, auth_headers):
        resp = client.get("/api/llm/connectors", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_openai_apikey_happy_path(self, client: TestClient, auth_headers, db):
        body = {
            "connector_type": "openai_apikey",
            "display_name": "My OpenAI",
            "api_key": "sk-proj-abc1234567890abcdef12",
            "model_hint": "gpt-5-mini",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["connector_type"] == "openai_apikey"
        assert data["display_name"] == "My OpenAI"
        # Credentials never returned
        assert "credentials" not in data
        assert "api_key" not in data

        # Audit event recorded
        event = (
            db.query(LlmAuditEvent).filter(LlmAuditEvent.target_connector_id == data["id"]).first()
        )
        assert event is not None
        assert event.event_type == "connector_created"

    def test_create_anthropic_apikey_happy_path(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "anthropic_apikey",
            "display_name": "My Claude",
            "api_key": "sk-ant-1234567890abcdef1234567890abcdef1234567890",
            "model_hint": "claude-haiku-4-5-20251001",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.json()

    def test_create_openai_compatible_happy_path(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "openai_compatible",
            "display_name": "Local Ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model_hint": "llama3",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["base_url_plain"] == "http://127.0.0.1:11434/v1"

    def test_create_openai_compatible_rejects_public_http(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "openai_compatible",
            "display_name": "Bad URL",
            "base_url": "http://example.com/v1",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 400

    def test_create_azure_openai_happy_path(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "azure_openai",
            "display_name": "Venue Azure",
            "api_key": "azure-secret-key-12345",
            "azure_resource_name": "venue-co",
            "azure_deployment_name": "gpt4o-prod",
            "azure_api_version": "2024-06-01",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["connector_type"] == "azure_openai"
        # Credentials (incl. azure config) are never echoed back.
        assert "api_key" not in data
        assert "azure_resource_name" not in data
        assert data["base_url_plain"] is None

    def test_create_azure_openai_requires_all_config_fields(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "azure_openai",
            "display_name": "Incomplete Azure",
            "api_key": "azure-secret-key-12345",
            "azure_resource_name": "venue-co",
            # missing deployment + api_version
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code in (400, 422)

    def test_rotate_azure_openai_config_without_recreating(
        self, client: TestClient, auth_headers, db, test_user
    ):
        create_body = {
            "connector_type": "azure_openai",
            "display_name": "Rotatable Azure",
            "api_key": "azure-secret-key-12345",
            "azure_resource_name": "old-resource",
            "azure_deployment_name": "old-deployment",
            "azure_api_version": "2024-02-01",
        }
        created = client.post("/api/llm/connectors", json=create_body, headers=auth_headers)
        assert created.status_code == 201, created.json()
        connector_id = created.json()["id"]

        # Rotate ONLY the deployment + resource — api_key omitted, must be kept.
        rotate = client.put(
            f"/api/llm/connectors/{connector_id}/credentials",
            json={
                "azure_resource_name": "new-resource",
                "azure_deployment_name": "new-deployment",
            },
            headers=auth_headers,
        )
        assert rotate.status_code == 200, rotate.json()

        # Verify the persisted blob carried forward the api_key + version.
        row = db.get(LlmConnector, connector_id)
        db.refresh(row)
        blob = json.loads(row.credentials)
        assert blob["api_key"] == "azure-secret-key-12345"
        assert blob["azure_resource_name"] == "new-resource"
        assert blob["azure_deployment_name"] == "new-deployment"
        assert blob["azure_api_version"] == "2024-02-01"

    def test_create_azure_openai_rejects_whitespace_only_config(
        self, client: TestClient, auth_headers
    ):
        body = {
            "connector_type": "azure_openai",
            "display_name": "Blank Azure",
            "api_key": "azure-secret-key-12345",
            "azure_resource_name": "venue-co",
            "azure_deployment_name": "   ",  # whitespace-only must be rejected
            "azure_api_version": "2024-06-01",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code in (400, 422), resp.json()

    def test_rotate_azure_openai_rejects_explicit_empty_field(
        self, client: TestClient, auth_headers, db, test_user
    ):
        create_body = {
            "connector_type": "azure_openai",
            "display_name": "Rotatable Azure",
            "api_key": "azure-secret-key-12345",
            "azure_resource_name": "old-resource",
            "azure_deployment_name": "old-deployment",
            "azure_api_version": "2024-02-01",
        }
        created = client.post("/api/llm/connectors", json=create_body, headers=auth_headers)
        assert created.status_code == 201, created.json()
        connector_id = created.json()["id"]

        # An explicit "" for one field must be rejected by the storage layer
        # (passed through to _build_azure_creds), not silently treated as
        # "omitted". A second valid field satisfies the schema-level
        # "at least one provided" check so the request reaches rotate_credentials.
        rotate = client.put(
            f"/api/llm/connectors/{connector_id}/credentials",
            json={"azure_resource_name": "", "azure_deployment_name": "still-valid"},
            headers=auth_headers,
        )
        assert rotate.status_code in (400, 422), rotate.json()

        # The original blob is untouched.
        row = db.get(LlmConnector, connector_id)
        db.refresh(row)
        blob = json.loads(row.credentials)
        assert blob["azure_resource_name"] == "old-resource"
        assert blob["azure_deployment_name"] == "old-deployment"

    def test_create_rejects_invalid_key_format(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "openai_apikey",
            "display_name": "Bad Key",
            "api_key": "not-a-valid-key",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 400

    def test_create_rejects_unknown_type(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "gemini_apikey",
            "display_name": "Future Gemini",
            "api_key": "sk-anything",
        }
        # Pydantic Literal rejects this with 422 before we reach our handler.
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code in (400, 422)

    def test_create_blocked_by_admin_policy(
        self, client: TestClient, auth_headers, db, admin_headers
    ):
        # Disable apikey connectors via admin policy
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_apikey_connectors_enabled": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200

        body = {
            "connector_type": "openai_apikey",
            "display_name": "Should Fail",
            "api_key": "sk-proj-abc1234567890abcdef12",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 403

    def test_pending_user_cannot_use_connectors(self, client: TestClient, pending_headers):
        resp = client.get("/api/llm/connectors", headers=pending_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_list(self, client: TestClient):
        resp = client.get("/api/llm/connectors")
        assert resp.status_code == 401

    def test_list_only_shows_own_connectors(self, client: TestClient, auth_headers, db, test_user):
        other = _make_other_dj(db)
        other_row = LlmConnector(
            user_id=other.id,
            connector_type="openai_apikey",
            display_name="Other's connector",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(other_row)
        db.commit()
        db.refresh(other_row)

        resp = client.get("/api/llm/connectors", headers=auth_headers)
        assert resp.status_code == 200
        assert all(r["user_id"] == test_user.id for r in resp.json())

    def test_404_when_accessing_other_dj_connector(self, client: TestClient, auth_headers, db):
        other = _make_other_dj(db)
        other_row = LlmConnector(
            user_id=other.id,
            connector_type="openai_apikey",
            display_name="Other's connector",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(other_row)
        db.commit()
        db.refresh(other_row)

        resp = client.delete(f"/api/llm/connectors/{other_row.id}", headers=auth_headers)
        assert resp.status_code == 404

    def test_delete_own_connector(self, client: TestClient, auth_headers, db, test_user):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Mine",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.delete(f"/api/llm/connectors/{row.id}", headers=auth_headers)
        assert resp.status_code == 204
        # Audit event recorded
        assert (
            db.query(LlmAuditEvent).filter(LlmAuditEvent.event_type == "connector_deleted").count()
            == 1
        )

    def test_rotate_credentials_audited(self, client: TestClient, auth_headers, db, test_user):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Mine",
            status="active",
            credentials=json.dumps({"api_key": "sk-old1234567890abcdef12"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.put(
            f"/api/llm/connectors/{row.id}/credentials",
            json={"api_key": "sk-new1234567890abcdef12"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.json()
        # Audit event for rotation written
        assert (
            db.query(LlmAuditEvent)
            .filter(LlmAuditEvent.event_type == "connector_credentials_rotated")
            .count()
            == 1
        )


# ---------- /connectors/{id}/test (health check) ----------
class TestHealthCheck:
    def test_test_endpoint_returns_ok(self, client: TestClient, auth_headers, db, test_user):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Mine",
            status="active",
            credentials=json.dumps({"api_key": "sk-key123"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(return_value=None),
        ):
            resp = client.post(f"/api/llm/connectors/{row.id}/test", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_test_returns_sanitized_error_on_auth_invalid(
        self, client: TestClient, auth_headers, db, test_user
    ):
        from app.services.llm.exceptions import AuthInvalid

        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Mine",
            status="active",
            credentials=json.dumps({"api_key": "sk-key123"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(side_effect=AuthInvalid("upstream secret should not leak")),
        ):
            resp = client.post(f"/api/llm/connectors/{row.id}/test", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["error_code"] == "auth_invalid"
        # Sanitised — no raw exception message
        assert "upstream secret should not leak" not in (data["message"] or "")

        db.refresh(row)
        assert row.status == "auth_invalid"


# ---------- Admin policy / oversight ----------
class TestAdminLlm:
    def test_get_policy(self, client: TestClient, admin_headers):
        resp = client.get("/api/admin/llm/policy", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "llm_apikey_connectors_enabled" in data
        assert "llm_compatible_connector_enabled" in data

    def test_patch_policy_toggles(self, client: TestClient, admin_headers):
        resp = client.patch(
            "/api/admin/llm/policy",
            json={
                "llm_apikey_connectors_enabled": False,
                "llm_compatible_connector_enabled": False,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_apikey_connectors_enabled"] is False
        assert data["llm_compatible_connector_enabled"] is False

    def test_non_admin_cannot_get_policy(self, client: TestClient, auth_headers):
        resp = client.get("/api/admin/llm/policy", headers=auth_headers)
        assert resp.status_code == 403

    def test_list_connectors_admin_shows_all(
        self, client: TestClient, admin_headers, db, test_user
    ):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Mine",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        resp = client.get("/api/admin/llm/connectors", headers=admin_headers)
        assert resp.status_code == 200
        users = [r["dj_username"] for r in resp.json()]
        assert "testuser" in users

    def test_force_revoke_clears_default(self, client: TestClient, admin_headers, db, test_user):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Mine",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        # Set as default
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_default_connector_id": row.id},
            headers=admin_headers,
        )
        assert resp.status_code == 200

        # Revoke
        resp = client.post(f"/api/admin/llm/connectors/{row.id}/revoke", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"

        # Default cleared
        resp = client.get("/api/admin/llm/policy", headers=admin_headers)
        assert resp.json()["llm_default_connector_id"] is None

        # Audit recorded
        assert (
            db.query(LlmAuditEvent)
            .filter(LlmAuditEvent.event_type == "connector_revoked_by_admin")
            .count()
            == 1
        )

    def test_usage_endpoint(self, client: TestClient, admin_headers, db, test_user):
        # Seed a connector and a call log row
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Mine",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        from app.services.llm.connector_storage import log_call

        log_call(
            db,
            connector_id=row.id,
            purpose="recommendation",
            status="ok",
            latency_ms=100,
            tokens_in=10,
            tokens_out=5,
        )
        db.commit()

        resp = client.get("/api/admin/llm/usage?days=30", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["days"] == 30
        assert any(r["connector_id"] == row.id for r in data["rows"])
