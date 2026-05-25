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

from app.services.llm.adapters._httpx_openai import build_healthcheck_request
from app.services.llm.adapters.anthropic_apikey import AnthropicApiKeyAdapter
from app.services.llm.adapters.azure_openai import AzureOpenAIAdapter, _build_azure_endpoint
from app.services.llm.adapters.gemini_apikey import GeminiApiKeyAdapter
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from app.services.llm.adapters.openrouter_apikey import (
    OPENROUTER_BASE_URL,
    OpenRouterApiKeyAdapter,
)
from app.services.llm.adapters.xai_apikey import XAI_BASE_URL, XaiApiKeyAdapter
from app.services.llm.base import ChatRequest, ContentBlock, Message, ToolSpec
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


# ---------------------------------------------------------------------------
# Shared healthcheck request
# ---------------------------------------------------------------------------
def test_healthcheck_request_imposes_no_tiny_output_cap():
    # A 1-token cap is consumed entirely by reasoning models' internal tokens,
    # producing zero output and an HTTP 400. The probe must leave the budget
    # to the provider's default.
    req = build_healthcheck_request()
    assert req.max_tokens is None


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


def _make_openrouter_connector(model_hint="openai/gpt-4o-mini"):
    return SimpleNamespace(
        connector_type="openrouter_apikey",
        credentials=json.dumps({"api_key": "sk-or-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
        model_hint=model_hint,
        base_url_plain=None,
    )


def _make_anthropic_connector():
    return SimpleNamespace(
        connector_type="anthropic_apikey",
        credentials=json.dumps({"api_key": "sk-ant-fake-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
        model_hint="claude-haiku-4-5-20251001",
        base_url_plain=None,
    )


def _make_xai_connector(model_hint="grok-3-mini"):
    return SimpleNamespace(
        connector_type="xai_apikey",
        credentials=json.dumps({"api_key": "xai-fake-key-1234567890123456789012"}),
        model_hint=model_hint,
        base_url_plain=None,
    )


# Non-secret placeholder — avoids committing an "AIza…"-shaped literal that trips
# secret scanners. The adapter doesn't validate key shape (that's done upstream),
# so any string works for transport-level assertions.
_GEMINI_TEST_KEY = "gemini-test-key-not-a-real-secret"


def _make_gemini_connector(model_hint="gemini-2.5-flash"):
    return SimpleNamespace(
        connector_type="gemini_apikey",
        credentials=json.dumps({"api_key": _GEMINI_TEST_KEY}),
        model_hint=model_hint,
        base_url_plain=None,
    )


def _gemini_success_body(text="hi"):
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
        ],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
        "modelVersion": "gemini-2.5-flash",
    }


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
    async def test_uses_max_completion_tokens_not_max_tokens(self):
        # OpenAI Platform's newer (GPT-5 / o-series) models reject the legacy
        # `max_tokens` field with HTTP 400 and require `max_completion_tokens`.
        connector = _make_openai_connector()
        adapter = OpenAIApiKeyAdapter(connector)
        request = ChatRequest(messages=[Message(role="user", content="hi")], max_tokens=100)

        client = _AsyncClient(_ok_response(_openai_success_body("pong")))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.chat(request)

        body = client.calls[0]["json"]
        assert body["max_completion_tokens"] == 100
        assert "max_tokens" not in body

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

    @pytest.mark.asyncio
    async def test_uses_legacy_max_tokens(self):
        # Third-party OpenAI-compatible servers (Ollama / vLLM / LMStudio) speak
        # the legacy `max_tokens` field — they must NOT receive max_completion_tokens.
        connector = _make_compatible_connector()
        adapter = OpenAICompatibleAdapter(connector)
        request = ChatRequest(messages=[Message(role="user", content="hi")], max_tokens=100)

        client = _AsyncClient(_ok_response(_openai_success_body("ok")))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.chat(request)

        body = client.calls[0]["json"]
        assert body["max_tokens"] == 100
        assert "max_completion_tokens" not in body


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
# Gemini API-key adapter (native generativelanguage API)
# ---------------------------------------------------------------------------
class TestGeminiApiKeyAdapter:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        request = ChatRequest(messages=[Message(role="user", content="hi")])

        client = _AsyncClient(_ok_response(_gemini_success_body("pong")))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(request)

        assert resp.text == "pong"
        assert resp.usage.prompt == 3
        assert resp.usage.completion == 1
        # API key goes in the x-goog-api-key header, never the URL/query string.
        assert client.calls[0]["headers"]["x-goog-api-key"] == _GEMINI_TEST_KEY
        assert _GEMINI_TEST_KEY not in client.calls[0]["url"]
        assert client.calls[0]["url"].endswith(":generateContent")
        assert "gemini-2.5-flash" in client.calls[0]["url"]

    @pytest.mark.asyncio
    async def test_system_prompt_maps_to_system_instruction(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        request = ChatRequest(
            messages=[Message(role="user", content="hi")],
            system="You are a DJ assistant.",
        )
        client = _AsyncClient(_ok_response(_gemini_success_body()))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            await adapter.chat(request)
        body = client.calls[0]["json"]
        assert body["systemInstruction"]["parts"][0]["text"] == "You are a DJ assistant."
        # Assistant turns map to the Gemini "model" role.
        assert body["contents"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_assistant_role_maps_to_model(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        request = ChatRequest(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
                Message(role="user", content="rank these"),
            ]
        )
        client = _AsyncClient(_ok_response(_gemini_success_body()))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            await adapter.chat(request)
        roles = [c["role"] for c in client.calls[0]["json"]["contents"]]
        assert roles == ["user", "model", "user"]

    @pytest.mark.asyncio
    async def test_tool_translation_and_parsing(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        tool = ToolSpec(
            name="search_queries",
            description="Generate search queries",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        request = ChatRequest(
            messages=[Message(role="user", content="go")],
            tools=[tool],
            force_tool="search_queries",
        )
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"functionCall": {"name": "search_queries", "args": {"q": "house"}}}
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 4},
        }
        client = _AsyncClient(_ok_response(body))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(request)

        # Request carried Gemini function_declarations + forced toolConfig.
        sent = client.calls[0]["json"]
        assert sent["tools"][0]["function_declarations"][0]["name"] == "search_queries"
        assert sent["toolConfig"]["function_calling_config"]["mode"] == "ANY"
        # Response parsed back into a canonical tool call.
        assert resp.stop_reason == "tool_use"
        assert resp.tool_calls[0].name == "search_queries"
        assert resp.tool_calls[0].input == {"q": "house"}

    @pytest.mark.asyncio
    async def test_401_maps_to_auth_invalid(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        resp = httpx.Response(
            401,
            request=httpx.Request("POST", "https://example.com"),
            json={"error": "bad key"},
        )
        client = _AsyncClient(resp)
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(AuthInvalid):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_403_maps_to_auth_invalid(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        resp = httpx.Response(
            403,
            request=httpx.Request("POST", "https://example.com"),
            json={"error": "forbidden"},
        )
        client = _AsyncClient(resp)
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(AuthInvalid):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_429_maps_to_rate_limited_with_retry_after(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        resp = httpx.Response(
            429,
            request=httpx.Request("POST", "https://example.com"),
            headers={"Retry-After": "17"},
            json={"error": "ratelimit"},
        )
        client = _AsyncClient(resp)
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(RateLimited) as exc_info:
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert exc_info.value.retry_after_seconds == 17

    @pytest.mark.asyncio
    async def test_5xx_maps_to_provider_unavailable(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        resp = httpx.Response(
            503,
            request=httpx.Request("POST", "https://example.com"),
            json={"error": "overloaded"},
        )
        client = _AsyncClient(resp)
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_timeout_maps_to_provider_unavailable(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        client = _AsyncClient(httpx.TimeoutException("timeout"))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_network_error_maps_to_provider_unavailable(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        client = _AsyncClient(httpx.ConnectError("boom"))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_json_body_raises_translation_error(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        bad = httpx.Response(
            200,
            request=httpx.Request("POST", "https://example.com"),
            content=b"not json at all",
        )
        client = _AsyncClient(bad)
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(ToolTranslationError):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_response_shape_raises_translation_error(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        client = _AsyncClient(_ok_response({"unexpected": "shape"}))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(ToolTranslationError):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_credentials_raise_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="gemini_apikey",
            credentials="not json at all",
            model_hint="gemini-2.5-flash",
            base_url_plain=None,
        )
        adapter = GeminiApiKeyAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="gemini_apikey",
            credentials=json.dumps({}),
            model_hint="gemini-2.5-flash",
            base_url_plain=None,
        )
        adapter = GeminiApiKeyAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_health_check_pings(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        client = _AsyncClient(_ok_response(_gemini_success_body()))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            await adapter.health_check()
        assert len(client.calls) == 1

    @pytest.mark.asyncio
    async def test_tool_result_message_requires_tool_call_id(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        with pytest.raises(ToolTranslationError):
            await adapter.chat(
                ChatRequest(messages=[Message(role="tool", content="result", tool_call_id=None)])
            )

    @pytest.mark.asyncio
    async def test_tool_result_message_maps_to_function_response(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        request = ChatRequest(
            messages=[
                Message(role="tool", content="42", tool_call_id="search_queries"),
            ]
        )
        client = _AsyncClient(_ok_response(_gemini_success_body()))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            await adapter.chat(request)
        contents = client.calls[0]["json"]["contents"]
        fr = contents[0]["parts"][0]["functionResponse"]
        assert fr["name"] == "search_queries"
        assert fr["response"] == {"content": "42"}

    @pytest.mark.asyncio
    async def test_system_role_message_is_dropped_from_contents(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        request = ChatRequest(
            messages=[
                Message(role="system", content="ignored legacy system msg"),
                Message(role="user", content="hi"),
            ]
        )
        client = _AsyncClient(_ok_response(_gemini_success_body()))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            await adapter.chat(request)
        contents = client.calls[0]["json"]["contents"]
        # The system message is not surfaced as a content turn.
        assert len(contents) == 1
        assert contents[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_list_content_blocks_flatten_to_text(self):
        """Regression: list-based content (ContentBlock objects AND raw dicts)
        must flatten into the part text, not silently drop to empty strings."""
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        obj_msg = Message(
            role="user",
            content=[ContentBlock(text="hello "), ContentBlock(text="world")],
        )
        # A dict-shaped block reaching the adapter unvalidated (model_construct
        # skips Pydantic coercion) must still contribute its text.
        dict_msg = Message.model_construct(role="assistant", content=[{"text": "ack"}])
        request = ChatRequest(messages=[obj_msg, dict_msg])
        client = _AsyncClient(_ok_response(_gemini_success_body()))
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            await adapter.chat(request)
        contents = client.calls[0]["json"]["contents"]
        assert contents[0]["parts"][0]["text"] == "hello world"
        assert contents[1]["parts"][0]["text"] == "ack"

    @pytest.mark.asyncio
    async def test_402_maps_to_quota_exceeded(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        resp = httpx.Response(
            402,
            request=httpx.Request("POST", "https://example.com"),
            json={"error": "billing"},
        )
        client = _AsyncClient(resp)
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(QuotaExceeded):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_400_maps_to_translation_error(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        resp = httpx.Response(
            400,
            request=httpx.Request("POST", "https://example.com"),
            json={"error": "bad request"},
        )
        client = _AsyncClient(resp)
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(ToolTranslationError):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_429_without_retry_after_is_none(self):
        connector = _make_gemini_connector()
        adapter = GeminiApiKeyAdapter(connector)
        resp = httpx.Response(
            429,
            request=httpx.Request("POST", "https://example.com"),
            json={"error": "ratelimit"},
        )
        client = _AsyncClient(resp)
        with patch(_GEMINI_HTTPX_PATH, return_value=client):
            with pytest.raises(RateLimited) as exc_info:
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert exc_info.value.retry_after_seconds is None


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
