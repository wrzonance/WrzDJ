"""Tests for the Anthropic API-key adapter contract."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.llm.adapters.anthropic_apikey import AnthropicApiKeyAdapter
from app.services.llm.base import ChatRequest, Message
from app.services.llm.exceptions import (
    AuthInvalid,
    RateLimited,
    ToolTranslationError,
)

_HTTPX_PATH = "app.services.llm.adapters._httpx_openai.httpx.AsyncClient"
_AZURE_HTTPX_PATH = "app.services.llm.adapters.azure_openai.httpx.AsyncClient"
_GEMINI_HTTPX_PATH = "app.services.llm.adapters.gemini_apikey.httpx.AsyncClient"

from tests.llm_adapter_test_helpers import _make_anthropic_connector


class _FakeAsyncClient:
    """Wrap a fake Anthropic client so it works with ``async with``.

    The real ``AsyncAnthropic`` client is an async context manager; the adapter
    uses ``async with self._client(...) as client`` to release HTTP resources.
    """

    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *exc):
        return False


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
            return_value=_FakeAsyncClient(
                SimpleNamespace(
                    messages=SimpleNamespace(create=AsyncMock(return_value=fake_message))
                )
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
            return_value=_FakeAsyncClient(
                SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=exc)))
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
            return_value=_FakeAsyncClient(
                SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=exc)))
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
