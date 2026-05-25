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
from app.services.llm.adapters.gemini_apikey import GeminiApiKeyAdapter
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from app.services.llm.base import ChatRequest, Message, ToolSpec
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)

_HTTPX_PATH = "app.services.llm.adapters._httpx_openai.httpx.AsyncClient"
_GEMINI_HTTPX_PATH = "app.services.llm.adapters.gemini_apikey.httpx.AsyncClient"


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


def _make_anthropic_connector():
    return SimpleNamespace(
        connector_type="anthropic_apikey",
        credentials=json.dumps({"api_key": "sk-ant-fake-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
        model_hint="claude-haiku-4-5-20251001",
        base_url_plain=None,
    )


def _make_gemini_connector(model_hint="gemini-2.5-flash"):
    return SimpleNamespace(
        connector_type="gemini_apikey",
        credentials=json.dumps({"api_key": "AIzaSyA1234567890abcdefghijklmnopqrstuv"}),
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
        assert client.calls[0]["headers"]["x-goog-api-key"] == (
            "AIzaSyA1234567890abcdefghijklmnopqrstuv"
        )
        assert "AIzaSy" not in client.calls[0]["url"]
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
