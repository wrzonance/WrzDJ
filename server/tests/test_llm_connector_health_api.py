"""Connector health and model catalogue API tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.models.llm_connector import LlmConnector


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
