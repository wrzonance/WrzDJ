"""Tests for the OpenAI / OpenAI-compatible / Anthropic adapters.

Each adapter is mocked at the HTTP boundary (httpx for OpenAI, anthropic SDK
for Anthropic) so we exercise the adapter logic without real network calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.llm.adapters.anthropic_apikey import AnthropicApiKeyAdapter
from app.services.llm.adapters.azure_openai import AzureOpenAIAdapter, _build_azure_endpoint
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.adapters.openai_compatible import OpenAICompatibleAdapter
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_openai_connector():
    return SimpleNamespace(
        connector_type="openai_apikey",
        credentials=json.dumps({"api_key": "sk-test-key-123456789012"}),
        model_hint="gpt-5-mini",
        base_url_plain=None,
    )


def _make_compatible_connector(base_url="http://127.0.0.1:11434/v1", bearer=None):
    creds = {"base_url": base_url, "bearer": bearer}
    return SimpleNamespace(
        connector_type="openai_compatible",
        credentials=json.dumps(creds),
        model_hint="llama3",
        base_url_plain=base_url,
    )


def _make_azure_connector(
    api_key="azure-secret-key",
    resource="my-resource",
    deployment="gpt4o",
    api_version="2024-06-01",
):
    creds = {
        "api_key": api_key,
        "azure_resource_name": resource,
        "azure_deployment_name": deployment,
        "azure_api_version": api_version,
    }
    return SimpleNamespace(
        connector_type="azure_openai",
        credentials=json.dumps(creds),
        model_hint=None,
        base_url_plain=None,
    )


def _make_anthropic_connector():
    return SimpleNamespace(
        connector_type="anthropic_apikey",
        credentials=json.dumps({"api_key": "sk-ant-fake-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
        model_hint="claude-haiku-4-5-20251001",
        base_url_plain=None,
    )


def _openai_success_body(text="hi"):
    return {
        "model": "gpt-5-mini",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }


def _ok_response(json_body):
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://example.com/v1/chat/completions"),
        json=json_body,
    )


class _AsyncClient:
    """Minimal httpx.AsyncClient stub for unit tests."""

    def __init__(self, response: httpx.Response | Exception):
        self._response = response
        self.calls: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


# ---------------------------------------------------------------------------
# OpenAI API-key adapter
# ---------------------------------------------------------------------------
class TestOpenAIApiKeyAdapter:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        connector = _make_openai_connector()
        adapter = OpenAIApiKeyAdapter(connector)
        request = ChatRequest(messages=[Message(role="user", content="hi")])

        client = _AsyncClient(_ok_response(_openai_success_body("pong")))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(request)

        assert resp.text == "pong"
        assert client.calls[0]["headers"]["Authorization"].startswith("Bearer ")
        assert client.calls[0]["url"].endswith("/chat/completions")

    @pytest.mark.asyncio
    async def test_401_maps_to_auth_invalid(self):
        connector = _make_openai_connector()
        adapter = OpenAIApiKeyAdapter(connector)
        resp = httpx.Response(
            401,
            request=httpx.Request("POST", "https://example.com"),
            json={"error": "bad key"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(AuthInvalid):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_429_maps_to_rate_limited_with_retry_after(self):
        connector = _make_openai_connector()
        adapter = OpenAIApiKeyAdapter(connector)
        resp = httpx.Response(
            429,
            request=httpx.Request("POST", "https://example.com"),
            headers={"Retry-After": "42"},
            json={"error": "ratelimit"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(RateLimited) as exc_info:
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert exc_info.value.retry_after_seconds == 42

    @pytest.mark.asyncio
    async def test_500_maps_to_provider_unavailable(self):
        connector = _make_openai_connector()
        adapter = OpenAIApiKeyAdapter(connector)
        resp = httpx.Response(
            502,
            request=httpx.Request("POST", "https://example.com"),
            json={"error": "boom"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_402_maps_to_quota_exceeded(self):
        connector = _make_openai_connector()
        adapter = OpenAIApiKeyAdapter(connector)
        resp = httpx.Response(
            402,
            request=httpx.Request("POST", "https://example.com"),
            json={"error": "billing"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(QuotaExceeded):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_timeout_maps_to_provider_unavailable(self):
        connector = _make_openai_connector()
        adapter = OpenAIApiKeyAdapter(connector)
        client = _AsyncClient(httpx.TimeoutException("timeout"))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_credentials_raise_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="openai_apikey",
            credentials="not json at all",
            model_hint="gpt-5-mini",
            base_url_plain=None,
        )
        adapter = OpenAIApiKeyAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="openai_apikey",
            credentials=json.dumps({}),
            model_hint="gpt-5-mini",
            base_url_plain=None,
        )
        adapter = OpenAIApiKeyAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))


# ---------------------------------------------------------------------------
# OpenAI-compatible adapter
# ---------------------------------------------------------------------------
class TestOpenAICompatibleAdapter:
    @pytest.mark.asyncio
    async def test_no_bearer_no_auth_header(self):
        connector = _make_compatible_connector()
        adapter = OpenAICompatibleAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("hello")))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))
        assert resp.text == "hello"
        assert "Authorization" not in client.calls[0]["headers"]

    @pytest.mark.asyncio
    async def test_with_bearer_sets_authorization(self):
        connector = _make_compatible_connector(bearer="abc123")
        adapter = OpenAICompatibleAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("hello")))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))
        assert client.calls[0]["headers"]["Authorization"] == "Bearer abc123"


# ---------------------------------------------------------------------------
# Anthropic API-key adapter
# ---------------------------------------------------------------------------
class TestAnthropicApiKeyAdapter:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        connector = _make_anthropic_connector()
        adapter = AnthropicApiKeyAdapter(connector)

        fake_message = SimpleNamespace(
            model="claude-haiku-4-5-20251001",
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="hi")],
            usage=SimpleNamespace(input_tokens=3, output_tokens=1),
        )

        with patch.object(
            adapter,
            "_client",
            return_value=SimpleNamespace(
                messages=SimpleNamespace(create=AsyncMock(return_value=fake_message))
            ),
        ):
            resp = await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))

        assert resp.text == "hi"
        assert resp.usage.prompt == 3
        assert resp.usage.completion == 1

    @pytest.mark.asyncio
    async def test_status_error_401_maps_to_auth_invalid(self):
        from anthropic import APIStatusError

        connector = _make_anthropic_connector()
        adapter = AnthropicApiKeyAdapter(connector)

        err_response = httpx.Response(
            401,
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
            json={"error": "bad"},
        )
        exc = APIStatusError("auth failed", response=err_response, body=None)

        with patch.object(
            adapter,
            "_client",
            return_value=SimpleNamespace(
                messages=SimpleNamespace(create=AsyncMock(side_effect=exc))
            ),
        ):
            with pytest.raises(AuthInvalid):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_status_error_429_maps_to_rate_limited(self):
        from anthropic import APIStatusError

        connector = _make_anthropic_connector()
        adapter = AnthropicApiKeyAdapter(connector)

        err_response = httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
            headers={"retry-after": "30"},
            json={"error": "limit"},
        )
        exc = APIStatusError("rate limited", response=err_response, body=None)

        with patch.object(
            adapter,
            "_client",
            return_value=SimpleNamespace(
                messages=SimpleNamespace(create=AsyncMock(side_effect=exc))
            ),
        ):
            with pytest.raises(RateLimited) as info:
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert info.value.retry_after_seconds == 30

    @pytest.mark.asyncio
    async def test_tool_call_message_requires_tool_call_id(self):
        connector = _make_anthropic_connector()
        adapter = AnthropicApiKeyAdapter(connector)
        # Build a tool message without tool_call_id — should raise
        with pytest.raises(ToolTranslationError):
            await adapter.chat(
                ChatRequest(messages=[Message(role="tool", content="result", tool_call_id=None)])
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
