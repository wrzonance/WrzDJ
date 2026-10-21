"""Tests for the Azure OpenAI adapter contract."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.services.llm.adapters.azure_openai import AzureOpenAIAdapter, _build_azure_endpoint
from app.services.llm.base import ChatRequest, Message
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)

_HTTPX_PATH = "app.services.llm.adapters._httpx_openai.httpx.AsyncClient"
_AZURE_HTTPX_PATH = "app.services.llm.adapters.azure_openai.httpx.AsyncClient"
_GEMINI_HTTPX_PATH = "app.services.llm.adapters.gemini_apikey.httpx.AsyncClient"

from tests.llm_adapter_test_helpers import (
    _AsyncClient,
    _make_azure_connector,
    _ok_response,
    _openai_success_body,
)


# ---------------------------------------------------------------------------
# Azure OpenAI adapter
# ---------------------------------------------------------------------------
class TestAzureOpenAIAdapter:
    @pytest.mark.asyncio
    async def test_happy_path_url_and_api_key_header(self):
        connector = _make_azure_connector(
            resource="acme", deployment="gpt4o", api_version="2024-06-01"
        )
        adapter = AzureOpenAIAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("pong")))
        with patch(_AZURE_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))

        assert resp.text == "pong"
        call = client.calls[0]
        # Per-deployment URL with api-version query string.
        assert call["url"] == (
            "https://acme.openai.azure.com/openai/deployments/gpt4o"
            "/chat/completions?api-version=2024-06-01"
        )
        # Azure uses the `api-key` header, NOT `Authorization: Bearer`.
        assert call["headers"]["api-key"] == "azure-secret-key"
        assert "Authorization" not in call["headers"]

    @pytest.mark.asyncio
    async def test_health_check_succeeds(self):
        connector = _make_azure_connector()
        adapter = AzureOpenAIAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("ok")))
        with patch(_AZURE_HTTPX_PATH, return_value=client):
            await adapter.health_check()
        assert client.calls[0]["headers"]["api-key"] == "azure-secret-key"

    @pytest.mark.asyncio
    async def test_uses_max_completion_tokens_not_max_tokens(self):
        # Azure serves the same OpenAI models, which reject legacy `max_tokens`.
        connector = _make_azure_connector()
        adapter = AzureOpenAIAdapter(connector)
        request = ChatRequest(messages=[Message(role="user", content="hi")], max_tokens=100)
        client = _AsyncClient(_ok_response(_openai_success_body("ok")))
        with patch(_AZURE_HTTPX_PATH, return_value=client):
            await adapter.chat(request)
        body = client.calls[0]["json"]
        assert body["max_completion_tokens"] == 100
        assert "max_tokens" not in body

    @pytest.mark.asyncio
    async def test_401_maps_to_auth_invalid(self):
        adapter = AzureOpenAIAdapter(_make_azure_connector())
        resp = httpx.Response(
            401, request=httpx.Request("POST", "https://acme.openai.azure.com"), json={}
        )
        with patch(_AZURE_HTTPX_PATH, return_value=_AsyncClient(resp)):
            with pytest.raises(AuthInvalid):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_429_maps_to_rate_limited_with_retry_after(self):
        adapter = AzureOpenAIAdapter(_make_azure_connector())
        resp = httpx.Response(
            429,
            request=httpx.Request("POST", "https://acme.openai.azure.com"),
            headers={"Retry-After": "17"},
            json={},
        )
        with patch(_AZURE_HTTPX_PATH, return_value=_AsyncClient(resp)):
            with pytest.raises(RateLimited) as info:
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert info.value.retry_after_seconds == 17

    @pytest.mark.asyncio
    async def test_5xx_maps_to_provider_unavailable(self):
        adapter = AzureOpenAIAdapter(_make_azure_connector())
        resp = httpx.Response(
            503, request=httpx.Request("POST", "https://acme.openai.azure.com"), json={}
        )
        with patch(_AZURE_HTTPX_PATH, return_value=_AsyncClient(resp)):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_402_maps_to_quota_exceeded(self):
        adapter = AzureOpenAIAdapter(_make_azure_connector())
        resp = httpx.Response(
            402, request=httpx.Request("POST", "https://acme.openai.azure.com"), json={}
        )
        with patch(_AZURE_HTTPX_PATH, return_value=_AsyncClient(resp)):
            with pytest.raises(QuotaExceeded):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_timeout_maps_to_provider_unavailable(self):
        adapter = AzureOpenAIAdapter(_make_azure_connector())
        client = _AsyncClient(httpx.TimeoutException("timeout"))
        with patch(_AZURE_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_json_body_raises_tool_translation_error(self):
        adapter = AzureOpenAIAdapter(_make_azure_connector())
        resp = httpx.Response(
            200,
            request=httpx.Request("POST", "https://acme.openai.azure.com"),
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        with patch(_AZURE_HTTPX_PATH, return_value=_AsyncClient(resp)):
            with pytest.raises(ToolTranslationError):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_missing_config_raises_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="azure_openai",
            credentials=json.dumps({"api_key": "k"}),  # missing azure_* fields
            model_hint=None,
            base_url_plain=None,
        )
        adapter = AzureOpenAIAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_credentials_raise_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="azure_openai",
            credentials="not json",
            model_hint=None,
            base_url_plain=None,
        )
        adapter = AzureOpenAIAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    def test_build_endpoint_encodes_and_validates(self):
        # Valid components compose the expected URL with the query encoded.
        url = _build_azure_endpoint("acme", "gpt-4o", "2024-06-01")
        assert url == (
            "https://acme.openai.azure.com/openai/deployments/gpt-4o"
            "/chat/completions?api-version=2024-06-01"
        )

    @pytest.mark.parametrize(
        ("resource", "deployment", "version"),
        [
            ("acme.evil.com/x", "gpt-4o", "2024-06-01"),  # authority rewrite
            ("acme", "../../admin", "2024-06-01"),  # path traversal
            ("acme", "gpt-4o", "2024-06-01&inject=1"),  # query injection
            ("acme/", "gpt-4o", "2024-06-01"),  # trailing slash in host
            ("acme", "gpt 4o", "2024-06-01"),  # whitespace in deployment
        ],
    )
    def test_build_endpoint_rejects_url_injection(self, resource, deployment, version):
        with pytest.raises(AuthInvalid):
            _build_azure_endpoint(resource, deployment, version)
