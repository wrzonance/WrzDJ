"""Tests for admin AI settings endpoints.

The legacy Anthropic env-var surface (api_key_configured / api_key_masked /
llm_model and GET /api/admin/ai/models) was removed — credentials live in the
LLM connector system (/api/admin/llm/*). These endpoints now expose only the
org-fallback gate and the public rate limit.
"""

from fastapi.testclient import TestClient


class TestAdminAISettings:
    def test_get_returns_all_fields(self, client: TestClient, admin_headers: dict):
        response = client.get("/api/admin/ai/settings", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"llm_enabled", "llm_rate_limit_per_minute"}

    def test_put_updates_settings(self, client: TestClient, admin_headers: dict):
        response = client.put(
            "/api/admin/ai/settings",
            headers=admin_headers,
            json={"llm_enabled": False, "llm_rate_limit_per_minute": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["llm_enabled"] is False
        assert data["llm_rate_limit_per_minute"] == 10

    def test_dj_gets_403(self, client: TestClient, auth_headers: dict):
        response = client.get("/api/admin/ai/settings", headers=auth_headers)
        assert response.status_code == 403

    def test_no_credential_fields_exposed(self, client: TestClient, admin_headers: dict):
        """Credential status lives on the connector surfaces, never here."""
        response = client.get("/api/admin/ai/settings", headers=admin_headers)
        data = response.json()
        assert "anthropic_api_key" not in data
        assert "api_key_configured" not in data
        assert "api_key_masked" not in data
        assert "llm_model" not in data
