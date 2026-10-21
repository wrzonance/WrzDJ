"""Tests for OpenAI and OpenAI-compatible adapter contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.services.llm.adapters._httpx_openai import build_healthcheck_request
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from app.services.llm.base import ChatRequest, Message
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
)

_HTTPX_PATH = "app.services.llm.adapters._httpx_openai.httpx.AsyncClient"

from tests.llm_adapter_test_helpers import (
    _AsyncClient,
    _make_compatible_connector,
    _make_openai_connector,
    _ok_response,
    _openai_success_body,
)


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

    def test_fails_closed_when_blob_missing_base_url(self):
        # base_url_plain is a display-only mirror; it must NEVER be used to route
        # traffic. If the encrypted blob lacks base_url, fail closed.
        connector = SimpleNamespace(
            connector_type="openai_compatible",
            credentials=json.dumps({"bearer": "abc"}),  # no base_url in the blob
            model_hint="llama3",
            base_url_plain="http://127.0.0.1:11434/v1",  # mirror present but ignored
        )
        adapter = OpenAICompatibleAdapter(connector)
        with pytest.raises(AuthInvalid):
            adapter._extract_credentials()
