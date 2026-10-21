"""Tests for OpenRouter and xAI OpenAI-protocol adapters."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.services.llm.adapters.openrouter_apikey import (
    OPENROUTER_BASE_URL,
    OpenRouterApiKeyAdapter,
)
from app.services.llm.adapters.xai_apikey import XAI_BASE_URL, XaiApiKeyAdapter
from app.services.llm.base import ChatRequest, ChatResponseChunk, Message, ToolSpec
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
    _make_openrouter_connector,
    _make_xai_connector,
    _ok_response,
    _openai_success_body,
)


# ---------------------------------------------------------------------------
# OpenRouter API-key adapter
# ---------------------------------------------------------------------------
class TestOpenRouterApiKeyAdapter:
    @pytest.mark.asyncio
    async def test_happy_path_uses_fixed_base_url_and_bearer(self):
        connector = _make_openrouter_connector()
        adapter = OpenRouterApiKeyAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("pong")))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))

        assert resp.text == "pong"
        # The api_key is surfaced as a Bearer token...
        assert client.calls[0]["headers"]["Authorization"].startswith("Bearer ")
        # ...and the request always targets the fixed OpenRouter endpoint.
        assert client.calls[0]["url"] == f"{OPENROUTER_BASE_URL}/chat/completions"

    @pytest.mark.asyncio
    async def test_model_hint_is_sent_as_model(self):
        connector = _make_openrouter_connector(model_hint="anthropic/claude-3.5-sonnet")
        adapter = OpenRouterApiKeyAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("ok")))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))
        assert client.calls[0]["json"]["model"] == "anthropic/claude-3.5-sonnet"

    @pytest.mark.asyncio
    async def test_falls_back_to_default_model_when_no_hint(self):
        connector = _make_openrouter_connector(model_hint=None)
        adapter = OpenRouterApiKeyAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("ok")))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))
        assert client.calls[0]["json"]["model"] == "openai/gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_stream_uses_openrouter_default_model_without_hint(self, monkeypatch):
        from app.services.llm.adapters import openai_compatible

        connector = _make_openrouter_connector(model_hint=None)
        adapter = OpenRouterApiKeyAdapter(connector)
        received: dict[str, object] = {}

        async def fake_stream(**kwargs):
            received.update(kwargs)
            yield ChatResponseChunk(done=True)

        monkeypatch.setattr(openai_compatible, "stream_openai_chat", fake_stream)
        chunks = [
            chunk
            async for chunk in adapter.stream(
                ChatRequest(messages=[Message(role="user", content="hi")])
            )
        ]

        assert chunks == [ChatResponseChunk(done=True)]
        assert received["fallback_model"] == "openai/gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_stream_uses_xai_default_model_without_hint(self, monkeypatch):
        from app.services.llm.adapters import openai_compatible

        connector = _make_xai_connector(model_hint=None)
        adapter = XaiApiKeyAdapter(connector)
        received: dict[str, object] = {}

        async def fake_stream(**kwargs):
            received.update(kwargs)
            yield ChatResponseChunk(done=True)

        monkeypatch.setattr(openai_compatible, "stream_openai_chat", fake_stream)
        chunks = [
            chunk
            async for chunk in adapter.stream(
                ChatRequest(messages=[Message(role="user", content="hi")])
            )
        ]

        assert chunks == [ChatResponseChunk(done=True)]
        assert received["fallback_model"] == "grok-3-mini"

    @pytest.mark.asyncio
    async def test_401_maps_to_auth_invalid(self):
        connector = _make_openrouter_connector()
        adapter = OpenRouterApiKeyAdapter(connector)
        resp = httpx.Response(
            401, request=httpx.Request("POST", "https://example.com"), json={"error": "bad"}
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(AuthInvalid):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_429_maps_to_rate_limited(self):
        connector = _make_openrouter_connector()
        adapter = OpenRouterApiKeyAdapter(connector)
        resp = httpx.Response(
            429,
            request=httpx.Request("POST", "https://example.com"),
            headers={"Retry-After": "12"},
            json={"error": "limit"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(RateLimited) as info:
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert info.value.retry_after_seconds == 12

    @pytest.mark.asyncio
    async def test_5xx_maps_to_provider_unavailable(self):
        connector = _make_openrouter_connector()
        adapter = OpenRouterApiKeyAdapter(connector)
        resp = httpx.Response(
            503, request=httpx.Request("POST", "https://example.com"), json={"error": "down"}
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_402_maps_to_quota_exceeded(self):
        connector = _make_openrouter_connector()
        adapter = OpenRouterApiKeyAdapter(connector)
        resp = httpx.Response(
            402, request=httpx.Request("POST", "https://example.com"), json={"error": "billing"}
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(QuotaExceeded):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_timeout_maps_to_provider_unavailable(self):
        connector = _make_openrouter_connector()
        adapter = OpenRouterApiKeyAdapter(connector)
        client = _AsyncClient(httpx.TimeoutException("timeout"))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_body_raises_tool_translation_error(self):
        connector = _make_openrouter_connector()
        adapter = OpenRouterApiKeyAdapter(connector)
        resp = httpx.Response(
            200,
            request=httpx.Request("POST", "https://example.com"),
            content=b"not json",
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ToolTranslationError):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_credentials_raise_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="openrouter_apikey",
            credentials="not json",
            model_hint="openai/gpt-4o-mini",
            base_url_plain=None,
        )
        adapter = OpenRouterApiKeyAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="openrouter_apikey",
            credentials=json.dumps({}),
            model_hint="openai/gpt-4o-mini",
            base_url_plain=None,
        )
        adapter = OpenRouterApiKeyAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.health_check()

    @pytest.mark.asyncio
    async def test_health_check_hits_fixed_base_url(self):
        connector = _make_openrouter_connector()
        adapter = OpenRouterApiKeyAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("ok")))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.health_check()
        assert client.calls[0]["url"] == f"{OPENROUTER_BASE_URL}/chat/completions"


# ---------------------------------------------------------------------------
# xAI Grok API-key adapter
# ---------------------------------------------------------------------------
def _openai_tool_call_body(name="pick", args='{"q": "house"}'):
    return {
        "model": "grok-3-mini",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": name, "arguments": args},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }


class TestXaiApiKeyAdapter:
    @pytest.mark.asyncio
    async def test_happy_path_uses_fixed_base_url_and_bearer(self):
        connector = _make_xai_connector()
        adapter = XaiApiKeyAdapter(connector)
        request = ChatRequest(messages=[Message(role="user", content="hi")])

        client = _AsyncClient(_ok_response(_openai_success_body("pong")))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(request)

        assert resp.text == "pong"
        # Base URL is pinned to xAI — never user-supplied.
        assert client.calls[0]["url"] == f"{XAI_BASE_URL}/chat/completions"
        # API key is sent as a bearer token.
        assert client.calls[0]["headers"]["Authorization"] == (
            "Bearer xai-fake-key-1234567890123456789012"
        )

    @pytest.mark.asyncio
    async def test_tool_use_via_inherited_openai_path(self):
        connector = _make_xai_connector()
        adapter = XaiApiKeyAdapter(connector)
        request = ChatRequest(
            messages=[Message(role="user", content="suggest")],
            tools=[
                ToolSpec(
                    name="pick",
                    description="pick a track",
                    input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
                )
            ],
            force_tool="pick",
        )

        client = _AsyncClient(_ok_response(_openai_tool_call_body()))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(request)

        # Tool-use translated through the inherited OpenAI-compatible path.
        assert resp.stop_reason == "tool_use"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "pick"
        assert resp.tool_calls[0].input == {"q": "house"}
        # The request body carried the OpenAI function-calling tool shape.
        sent = client.calls[0]["json"]
        assert sent["tools"][0]["function"]["name"] == "pick"
        assert sent["tool_choice"]["function"]["name"] == "pick"

    @pytest.mark.asyncio
    async def test_401_maps_to_auth_invalid(self):
        connector = _make_xai_connector()
        adapter = XaiApiKeyAdapter(connector)
        resp = httpx.Response(
            401,
            request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
            json={"error": "bad key"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(AuthInvalid):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_429_maps_to_rate_limited_with_retry_after(self):
        connector = _make_xai_connector()
        adapter = XaiApiKeyAdapter(connector)
        resp = httpx.Response(
            429,
            request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
            headers={"Retry-After": "17"},
            json={"error": "ratelimit"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(RateLimited) as exc_info:
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert exc_info.value.retry_after_seconds == 17

    @pytest.mark.asyncio
    async def test_5xx_maps_to_provider_unavailable_with_xai_context(self):
        connector = _make_xai_connector()
        adapter = XaiApiKeyAdapter(connector)
        resp = httpx.Response(
            503,
            request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
            json={"error": "boom"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable) as exc_info:
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert "xAI" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_402_maps_to_quota_exceeded(self):
        connector = _make_xai_connector()
        adapter = XaiApiKeyAdapter(connector)
        resp = httpx.Response(
            402,
            request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
            json={"error": "billing"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(QuotaExceeded):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_timeout_maps_to_provider_unavailable(self):
        connector = _make_xai_connector()
        adapter = XaiApiKeyAdapter(connector)
        client = _AsyncClient(httpx.TimeoutException("timeout"))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_response_raises_tool_translation_error(self):
        connector = _make_xai_connector()
        adapter = XaiApiKeyAdapter(connector)
        # 200 with a body that has no choices -> parse error.
        resp = httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
            json={"unexpected": "shape"},
        )
        client = _AsyncClient(resp)
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ToolTranslationError):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_credentials_raise_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="xai_apikey",
            credentials="not json at all",
            model_hint="grok-3-mini",
            base_url_plain=None,
        )
        adapter = XaiApiKeyAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="xai_apikey",
            credentials=json.dumps({}),
            model_hint="grok-3-mini",
            base_url_plain=None,
        )
        adapter = XaiApiKeyAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_health_check_pings_fixed_base_url(self):
        connector = _make_xai_connector()
        adapter = XaiApiKeyAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("ok")))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.health_check()
        assert client.calls[0]["url"] == f"{XAI_BASE_URL}/chat/completions"

    @pytest.mark.asyncio
    async def test_default_model_used_when_no_model_hint(self):
        connector = _make_xai_connector(model_hint=None)
        adapter = XaiApiKeyAdapter(connector)
        client = _AsyncClient(_ok_response(_openai_success_body("ok")))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert client.calls[0]["json"]["model"] == "grok-3-mini"
