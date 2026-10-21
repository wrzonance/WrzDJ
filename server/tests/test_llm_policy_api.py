"""LLM policy API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


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
