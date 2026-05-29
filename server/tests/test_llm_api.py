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

    def test_create_openrouter_apikey_happy_path(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "openrouter_apikey",
            "display_name": "My OpenRouter",
            "api_key": "sk-or-v1-1234567890abcdef1234567890abcdef",
            "model_hint": "openai/gpt-4o-mini",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["connector_type"] == "openrouter_apikey"
        assert data["model_hint"] == "openai/gpt-4o-mini"
        assert "credentials" not in data
        assert "api_key" not in data

    def test_create_openrouter_rejects_non_openrouter_key(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "openrouter_apikey",
            "display_name": "Wrong prefix",
            "api_key": "sk-proj-abc1234567890abcdef12",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 400

    def test_create_openrouter_blocked_by_apikey_policy(
        self, client: TestClient, auth_headers, admin_headers
    ):
        # OpenRouter is gated by the generic api-key flag (no per-provider flag).
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_apikey_connectors_enabled": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.json()
        body = {
            "connector_type": "openrouter_apikey",
            "display_name": "Should Fail",
            "api_key": "sk-or-v1-1234567890abcdef1234567890abcdef",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 403

    def test_create_xai_apikey_happy_path(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "xai_apikey",
            "display_name": "My Grok",
            "api_key": "xai-1234567890abcdef1234567890abcdef",
            "model_hint": "grok-3-mini",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["connector_type"] == "xai_apikey"
        assert "api_key" not in data

    def test_create_xai_apikey_rejects_invalid_key_format(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "xai_apikey",
            "display_name": "Bad Grok",
            # Missing the xai- prefix.
            "api_key": "sk-1234567890abcdef1234567890",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 400

    def test_create_xai_apikey_blocked_by_apikey_policy(
        self, client: TestClient, auth_headers, admin_headers
    ):
        # The generic api-key policy flag also gates xAI connectors.
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_apikey_connectors_enabled": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.json()
        body = {
            "connector_type": "xai_apikey",
            "display_name": "Blocked Grok",
            "api_key": "xai-1234567890abcdef1234567890abcdef",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 403

    def test_create_gemini_apikey_happy_path(self, client: TestClient, auth_headers):
        # Built at runtime (valid 39-char shape) so no "AIza…" literal is committed.
        gemini_key = "AIza" + ("A" * 35)
        body = {
            "connector_type": "gemini_apikey",
            "display_name": "My Gemini",
            "api_key": gemini_key,
            "model_hint": "gemini-2.5-flash",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["connector_type"] == "gemini_apikey"
        assert "api_key" not in data

    def test_create_gemini_rejects_non_google_key(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "gemini_apikey",
            "display_name": "Bad Gemini",
            "api_key": "sk-not-a-google-key",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 400

    def test_gemini_blocked_by_apikey_policy(self, client: TestClient, auth_headers, admin_headers):
        # Gemini reuses the generic api-key policy flag — no per-provider toggle.
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_apikey_connectors_enabled": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        gemini_key = "AIza" + ("A" * 35)
        body = {
            "connector_type": "gemini_apikey",
            "display_name": "Should Fail",
            "api_key": gemini_key,
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 403

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

    def test_create_bedrock_happy_path(self, client: TestClient, auth_headers, db, test_user):
        body = {
            "connector_type": "bedrock",
            "display_name": "My Bedrock",
            "aws_access_key_id": "AKIAEXAMPLEKEY12345",
            "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
            "aws_region": "us-east-1",
            "aws_model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["connector_type"] == "bedrock"
        # base_url_plain stays null — no plaintext credential surface for bedrock.
        assert data["base_url_plain"] is None
        # Verify the encrypted blob round-trips with all four AWS fields.
        row = db.query(LlmConnector).filter(LlmConnector.id == data["id"]).one()
        blob = json.loads(row.credentials)
        assert blob["aws_access_key_id"] == "AKIAEXAMPLEKEY12345"
        assert blob["aws_secret_access_key"] == "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
        assert blob["aws_region"] == "us-east-1"
        assert blob["aws_model_id"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"

    def test_create_bedrock_requires_all_aws_fields(self, client: TestClient, auth_headers):
        body = {
            "connector_type": "bedrock",
            "display_name": "Incomplete",
            "aws_access_key_id": "AKIAEXAMPLEKEY12345",
            "aws_secret_access_key": "secret",
            # missing aws_region + aws_model_id
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        # model_validator → ValueError → 422 (pydantic) before our handler
        assert resp.status_code in (400, 422)

    def test_create_bedrock_blocked_when_apikey_connectors_disabled(
        self, client: TestClient, auth_headers, db
    ):
        from app.services.system_settings import get_system_settings

        settings = get_system_settings(db)
        settings.llm_apikey_connectors_enabled = False
        db.commit()

        body = {
            "connector_type": "bedrock",
            "display_name": "Blocked Bedrock",
            "aws_access_key_id": "AKIAEXAMPLEKEY12345",
            "aws_secret_access_key": "secret",
            "aws_region": "us-east-1",
            "aws_model_id": "meta.llama3-70b-instruct-v1:0",
        }
        resp = client.post("/api/llm/connectors", json=body, headers=auth_headers)
        assert resp.status_code == 403

    def test_rotate_bedrock_credentials(self, client: TestClient, auth_headers, db, test_user):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="bedrock",
            display_name="Rotatable",
            status="active",
            credentials=json.dumps(
                {
                    "aws_access_key_id": "AKIAOLDKEY1234567890",
                    "aws_secret_access_key": "oldsecret",
                    "aws_region": "us-east-1",
                    "aws_model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                }
            ),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        # Rotate only the secret — other fields must be preserved.
        resp = client.put(
            f"/api/llm/connectors/{row.id}/credentials",
            json={"aws_secret_access_key": "newsecret"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.json()
        db.refresh(row)
        blob = json.loads(row.credentials)
        assert blob["aws_secret_access_key"] == "newsecret"
        assert blob["aws_access_key_id"] == "AKIAOLDKEY1234567890"
        assert blob["aws_region"] == "us-east-1"
        assert blob["aws_model_id"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"

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
            "connector_type": "unknown_provider",
            "display_name": "Future Provider",
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

    def test_delete_own_connector_clears_system_default(
        self, client: TestClient, auth_headers, db, test_user
    ):
        from app.services.system_settings import get_system_settings

        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="DefaultMine",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        settings = get_system_settings(db)
        settings.llm_default_connector_id = row.id
        db.commit()

        resp = client.delete(f"/api/llm/connectors/{row.id}", headers=auth_headers)
        assert resp.status_code == 204

        db.expire_all()
        settings = get_system_settings(db)
        assert settings.llm_default_connector_id is None

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


# ---------- OpenRouter model catalogue endpoint ----------
class TestOpenRouterModels:
    def test_returns_cached_model_list(self, client: TestClient, auth_headers):
        from app.schemas.ai_settings import AIModelInfo

        models = [
            AIModelInfo(id="openai/gpt-4o-mini", name="GPT-4o mini"),
            AIModelInfo(id="anthropic/claude-3.5-sonnet", name="Claude 3.5 Sonnet"),
        ]
        with patch(
            "app.api.llm.get_openrouter_models",
            new=AsyncMock(return_value=models),
        ):
            resp = client.get("/api/llm/openrouter/models", headers=auth_headers)
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()["models"]]
        assert ids == ["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"]

    def test_returns_empty_when_catalogue_unavailable(self, client: TestClient, auth_headers):
        with patch("app.api.llm.get_openrouter_models", new=AsyncMock(return_value=[])):
            resp = client.get("/api/llm/openrouter/models", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["models"] == []

    def test_requires_authentication(self, client: TestClient):
        resp = client.get("/api/llm/openrouter/models")
        assert resp.status_code == 401


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

    def test_patch_policy_rejects_clear_default_with_id(self, client: TestClient, admin_headers):
        # clear_default and a non-null default id are contradictory.
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"clear_default": True, "llm_default_connector_id": 1},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_policy_exposes_retention_default(self, client: TestClient, admin_headers):
        # Issue #342: retention is surfaced via the policy endpoint and defaults to 30.
        resp = client.get("/api/admin/llm/policy", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["llm_call_log_retention_days"] == 30

    def test_patch_retention_persists(self, client: TestClient, admin_headers, db):
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_call_log_retention_days": 90},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["llm_call_log_retention_days"] == 90

        # Persisted to the DB-backed singleton, visible on a fresh GET.
        resp = client.get("/api/admin/llm/policy", headers=admin_headers)
        assert resp.json()["llm_call_log_retention_days"] == 90

        from app.services.system_settings import get_system_settings

        assert get_system_settings(db).llm_call_log_retention_days == 90

    def test_patch_retention_below_min_rejected(self, client: TestClient, admin_headers):
        # Sanity bound: minimum 7 days. Rejected at the API level (422).
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_call_log_retention_days": 6},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_patch_retention_above_max_rejected(self, client: TestClient, admin_headers):
        # Sanity bound: maximum 365 days. Rejected at the API level (422).
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_call_log_retention_days": 366},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_patch_retention_accepts_boundaries(self, client: TestClient, admin_headers):
        for value in (7, 365):
            resp = client.patch(
                "/api/admin/llm/policy",
                json={"llm_call_log_retention_days": value},
                headers=admin_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["llm_call_log_retention_days"] == value

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

    # ---------- Monthly token cap (issue #339) ----------

    def test_connectors_listing_includes_cap_and_usage(
        self, client: TestClient, admin_headers, db, test_user
    ):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Capped",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
            monthly_token_cap=1000,
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
            latency_ms=10,
            tokens_in=120,
            tokens_out=80,
        )
        db.commit()

        resp = client.get("/api/admin/llm/connectors", headers=admin_headers)
        assert resp.status_code == 200
        listed = next(r for r in resp.json() if r["id"] == row.id)
        assert listed["monthly_token_cap"] == 1000
        assert listed["current_month_tokens"] == 200

    def test_set_connector_cap(self, client: TestClient, admin_headers, db, test_user):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="C",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={"monthly_token_cap": 50000},
        )
        assert resp.status_code == 200
        assert resp.json()["monthly_token_cap"] == 50000

        # Clearing it (null) returns it to unlimited.
        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={"monthly_token_cap": None},
        )
        assert resp.status_code == 200
        assert resp.json()["monthly_token_cap"] is None

        # Audit row written (reuses policy_changed event type).
        assert (
            db.query(LlmAuditEvent)
            .filter(
                LlmAuditEvent.event_type == "policy_changed",
                LlmAuditEvent.target_connector_id == row.id,
            )
            .count()
            == 2
        )

    def test_set_cap_zero_allowed(self, client: TestClient, admin_headers, db, test_user):
        # 0 is a valid cap meaning "no further calls this month".
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Zero",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={"monthly_token_cap": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["monthly_token_cap"] == 0

    def test_set_cap_rejects_negative(self, client: TestClient, admin_headers, db, test_user):
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="Neg",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={"monthly_token_cap": -5},
        )
        assert resp.status_code == 422  # Pydantic ge=0 rejection

    def test_set_cap_rejects_empty_body(self, client: TestClient, admin_headers, db, test_user):
        # monthly_token_cap is required: an empty {} body must be rejected (422),
        # not silently treated as null — otherwise an accidental no-field PATCH
        # would wipe a configured cap (CodeRabbit #377).
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="EmptyBody",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
            monthly_token_cap=1000,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=admin_headers,
            json={},
        )
        assert resp.status_code == 422
        # The cap must be untouched by the rejected request.
        db.refresh(row)
        assert row.monthly_token_cap == 1000

    def test_set_cap_404_for_missing_connector(self, client: TestClient, admin_headers):
        resp = client.patch(
            "/api/admin/llm/connectors/999999/cap",
            headers=admin_headers,
            json={"monthly_token_cap": 100},
        )
        assert resp.status_code == 404

    def test_set_cap_requires_admin(self, client: TestClient, auth_headers, db, test_user):
        # A non-admin (plain DJ) must be rejected even for their own connector.
        row = LlmConnector(
            user_id=test_user.id,
            connector_type="openai_apikey",
            display_name="C3",
            status="active",
            credentials=json.dumps({"api_key": "sk-x"}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        resp = client.patch(
            f"/api/admin/llm/connectors/{row.id}/cap",
            headers=auth_headers,
            json={"monthly_token_cap": 100},
        )
        assert resp.status_code == 403


# ---------- DJ-readable policy endpoint (issue #355) ----------
class TestDjPolicyEndpoint:
    """GET /api/llm/policy — DJ-scoped, non-sensitive policy surface.

    A normal DJ must be able to read which connector types the admin has
    enabled so the settings/ai page can fail closed instead of offering
    providers that the server will reject at create time.
    """

    def test_dj_can_read_policy_defaults_all_allowed(self, client: TestClient, auth_headers):
        resp = client.get("/api/llm/policy", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Defaults: both flags enabled.
        assert data["llm_apikey_connectors_enabled"] is True
        assert data["llm_compatible_connector_enabled"] is True
        # The allowed-types set must cover every valid connector type by default.
        assert set(data["allowed_connector_types"]) == {
            "openai_apikey",
            "anthropic_apikey",
            "openai_compatible",
            "gemini_apikey",
            "azure_openai",
            "bedrock",
            "openrouter_apikey",
            "xai_apikey",
        }
        # Must NOT leak the sensitive admin-only default-connector pointer.
        assert "llm_default_connector_id" not in data

    def test_policy_reflects_apikey_disabled(self, client: TestClient, auth_headers, admin_headers):
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_apikey_connectors_enabled": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200

        resp = client.get("/api/llm/policy", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_apikey_connectors_enabled"] is False
        assert data["llm_compatible_connector_enabled"] is True
        # Only the openai_compatible type remains allowed.
        assert data["allowed_connector_types"] == ["openai_compatible"]

    def test_policy_reflects_compatible_disabled(
        self, client: TestClient, auth_headers, admin_headers
    ):
        resp = client.patch(
            "/api/admin/llm/policy",
            json={"llm_compatible_connector_enabled": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200

        resp = client.get("/api/llm/policy", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_compatible_connector_enabled"] is False
        assert "openai_compatible" not in data["allowed_connector_types"]
        # API-key types still present.
        assert "openai_apikey" in data["allowed_connector_types"]

    def test_policy_all_disabled_yields_empty_allowed(
        self, client: TestClient, auth_headers, admin_headers
    ):
        resp = client.patch(
            "/api/admin/llm/policy",
            json={
                "llm_apikey_connectors_enabled": False,
                "llm_compatible_connector_enabled": False,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200

        resp = client.get("/api/llm/policy", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["allowed_connector_types"] == []

    def test_pending_user_cannot_read_policy(self, client: TestClient, pending_headers):
        resp = client.get("/api/llm/policy", headers=pending_headers)
        assert resp.status_code == 403

    def test_unauthenticated_cannot_read_policy(self, client: TestClient):
        resp = client.get("/api/llm/policy")
        assert resp.status_code == 401
