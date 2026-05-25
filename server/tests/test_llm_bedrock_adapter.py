"""Tests for the AWS Bedrock adapter (SigV4 over httpx, no boto3).

The HTTP boundary is mocked — we never reach real AWS. Both Bedrock Claude
(``anthropic.*``) and Bedrock Llama (``meta.*``) model families are exercised
because their request bodies and tool semantics differ.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.services.llm.adapters.bedrock import BedrockAdapter, model_family
from app.services.llm.base import ChatRequest, Message, ToolSpec
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)

_HTTPX_PATH = "app.services.llm.adapters.bedrock.httpx.AsyncClient"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _bedrock_connector(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0"):
    return SimpleNamespace(
        connector_type="bedrock",
        credentials=json.dumps(
            {
                "aws_access_key_id": "AKIDEXAMPLE",
                "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
                "aws_region": "us-east-1",
                "aws_model_id": model_id,
            }
        ),
        model_hint=None,
        base_url_plain=None,
    )


def _anthropic_body(text="hi"):
    return {
        "model": "claude",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }


def _anthropic_tool_body(name, tool_input):
    return {
        "model": "claude",
        "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": "tu_1", "name": name, "input": tool_input}],
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }


def _llama_body(generation, stop_reason="stop"):
    return {
        "generation": generation,
        "stop_reason": stop_reason,
        "prompt_token_count": 7,
        "generation_token_count": 4,
    }


def _ok(json_body):
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://bedrock-runtime.us-east-1.amazonaws.com/x"),
        json=json_body,
    )


class _AsyncClient:
    def __init__(self, response):
        self._response = response
        self.calls: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, content=None, headers=None):
        self.calls.append({"url": url, "content": content, "headers": headers})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


# ---------------------------------------------------------------------------
# model family detection
# ---------------------------------------------------------------------------
class TestModelFamily:
    def test_anthropic_family(self):
        assert model_family("anthropic.claude-3-5-sonnet-20241022-v2:0") == "anthropic"

    def test_anthropic_inference_profile_prefix(self):
        assert model_family("us.anthropic.claude-3-5-haiku-20241022-v1:0") == "anthropic"

    def test_llama_family_meta_prefix(self):
        assert model_family("meta.llama3-70b-instruct-v1:0") == "llama"

    def test_llama_family_name_match(self):
        assert model_family("us.meta.llama3-1-8b-instruct-v1:0") == "llama"

    def test_unknown_family_raises(self):
        with pytest.raises(ToolTranslationError):
            model_family("amazon.titan-text-express-v1")


# ---------------------------------------------------------------------------
# Bedrock Claude (anthropic.*)
# ---------------------------------------------------------------------------
class TestBedrockClaude:
    @pytest.mark.asyncio
    async def test_happy_path_signs_and_parses(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(_ok(_anthropic_body("pong")))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))

        assert resp.text == "pong"
        assert resp.usage.prompt == 3
        assert resp.usage.completion == 1
        assert resp.model == "anthropic.claude-3-5-sonnet-20241022-v2:0"
        # SigV4 auth — not a bearer token.
        auth = client.calls[0]["headers"]["Authorization"]
        assert auth.startswith("AWS4-HMAC-SHA256 ")
        assert "X-Amz-Date" in client.calls[0]["headers"]
        assert client.calls[0]["url"].endswith(
            "/model/anthropic.claude-3-5-sonnet-20241022-v2:0/invoke"
        )

    @pytest.mark.asyncio
    async def test_request_body_uses_anthropic_schema(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(_ok(_anthropic_body()))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.chat(
                ChatRequest(messages=[Message(role="user", content="hi")], system="be terse")
            )
        body = json.loads(client.calls[0]["content"])
        assert body["anthropic_version"] == "bedrock-2023-05-31"
        assert body["system"] == "be terse"
        assert body["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_tool_use_reuses_anthropic_translation(self):
        adapter = BedrockAdapter(_bedrock_connector())
        tool = ToolSpec(name="pick", description="pick a song", input_schema={"type": "object"})
        client = _AsyncClient(_ok(_anthropic_tool_body("pick", {"q": "house"})))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(
                ChatRequest(
                    messages=[Message(role="user", content="hi")],
                    tools=[tool],
                    force_tool="pick",
                )
            )
        assert resp.stop_reason == "tool_use"
        assert resp.tool_calls[0].name == "pick"
        assert resp.tool_calls[0].input == {"q": "house"}
        body = json.loads(client.calls[0]["content"])
        assert body["tools"][0]["name"] == "pick"
        assert body["tool_choice"] == {"type": "tool", "name": "pick"}


# ---------------------------------------------------------------------------
# Bedrock Llama (meta.*)
# ---------------------------------------------------------------------------
class TestBedrockLlama:
    @pytest.mark.asyncio
    async def test_happy_path_prompt_body(self):
        adapter = BedrockAdapter(_bedrock_connector("meta.llama3-70b-instruct-v1:0"))
        client = _AsyncClient(_ok(_llama_body("hello there")))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))
        assert resp.text == "hello there"
        assert resp.stop_reason == "end_turn"
        assert resp.usage.prompt == 7
        assert resp.usage.completion == 4
        assert resp.model == "meta.llama3-70b-instruct-v1:0"
        body = json.loads(client.calls[0]["content"])
        # Llama uses a prompt string, not anthropic messages.
        assert "prompt" in body
        assert "anthropic_version" not in body
        assert "<|begin_of_text|>" in body["prompt"]

    @pytest.mark.asyncio
    async def test_length_stop_reason_maps_to_max_tokens(self):
        adapter = BedrockAdapter(_bedrock_connector("meta.llama3-70b-instruct-v1:0"))
        client = _AsyncClient(_ok(_llama_body("partial", stop_reason="length")))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(ChatRequest(messages=[Message(role="user", content="hi")]))
        assert resp.stop_reason == "max_tokens"

    @pytest.mark.asyncio
    async def test_tool_call_parsed_from_generation_json(self):
        adapter = BedrockAdapter(_bedrock_connector("meta.llama3-1-70b-instruct-v1:0"))
        tool = ToolSpec(name="pick", description="pick", input_schema={"type": "object"})
        generation = '{"name": "pick", "input": {"q": "techno"}}'
        client = _AsyncClient(_ok(_llama_body(generation)))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(
                ChatRequest(
                    messages=[Message(role="user", content="hi")],
                    tools=[tool],
                    force_tool="pick",
                )
            )
        assert resp.stop_reason == "tool_use"
        assert resp.tool_calls[0].name == "pick"
        assert resp.tool_calls[0].input == {"q": "techno"}
        # Tool instructions are embedded in the prompt for Llama.
        body = json.loads(client.calls[0]["content"])
        assert "pick" in body["prompt"]

    @pytest.mark.asyncio
    async def test_unknown_tool_name_in_generation_is_plain_text(self):
        adapter = BedrockAdapter(_bedrock_connector("meta.llama3-70b-instruct-v1:0"))
        tool = ToolSpec(name="pick", description="pick", input_schema={"type": "object"})
        generation = '{"name": "other", "input": {}}'
        client = _AsyncClient(_ok(_llama_body(generation)))
        with patch(_HTTPX_PATH, return_value=client):
            resp = await adapter.chat(
                ChatRequest(messages=[Message(role="user", content="hi")], tools=[tool])
            )
        assert resp.tool_calls == []
        assert resp.text == generation


# ---------------------------------------------------------------------------
# Error mapping (shared) — exercised via the Claude family
# ---------------------------------------------------------------------------
class TestBedrockErrorMapping:
    def _err(self, status, headers=None):
        return httpx.Response(
            status,
            request=httpx.Request("POST", "https://bedrock-runtime.us-east-1.amazonaws.com/x"),
            headers=headers or {},
            json={"message": "x"},
        )

    @pytest.mark.asyncio
    async def test_401_maps_to_auth_invalid(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(self._err(401))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(AuthInvalid):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_403_maps_to_auth_invalid(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(self._err(403))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(AuthInvalid):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_429_maps_to_rate_limited(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(self._err(429, headers={"Retry-After": "12"}))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(RateLimited) as info:
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))
        assert info.value.retry_after_seconds == 12

    @pytest.mark.asyncio
    async def test_throttling_exception_400_maps_to_rate_limited(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(self._err(400, headers={"x-amzn-errortype": "ThrottlingException"}))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(RateLimited):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_402_maps_to_quota_exceeded(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(self._err(402))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(QuotaExceeded):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_500_maps_to_provider_unavailable(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(self._err(503))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_timeout_maps_to_provider_unavailable(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(httpx.TimeoutException("timeout"))
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ProviderUnavailable):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_malformed_body_400_maps_to_tool_translation_error(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(self._err(400))  # no throttle header
        with patch(_HTTPX_PATH, return_value=client):
            with pytest.raises(ToolTranslationError):
                await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))


# ---------------------------------------------------------------------------
# Credential extraction
# ---------------------------------------------------------------------------
class TestBedrockCredentials:
    @pytest.mark.asyncio
    async def test_malformed_credentials_raise_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="bedrock",
            credentials="not json",
            model_hint=None,
            base_url_plain=None,
        )
        adapter = BedrockAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_missing_field_raises_auth_invalid(self):
        connector = SimpleNamespace(
            connector_type="bedrock",
            credentials=json.dumps(
                {
                    "aws_access_key_id": "AKID",
                    "aws_secret_access_key": "secret",
                    "aws_region": "us-east-1",
                    # missing aws_model_id
                }
            ),
            model_hint=None,
            base_url_plain=None,
        )
        adapter = BedrockAdapter(connector)
        with pytest.raises(AuthInvalid):
            await adapter.chat(ChatRequest(messages=[Message(role="user", content="x")]))

    @pytest.mark.asyncio
    async def test_health_check_pings(self):
        adapter = BedrockAdapter(_bedrock_connector())
        client = _AsyncClient(_ok(_anthropic_body("ok")))
        with patch(_HTTPX_PATH, return_value=client):
            await adapter.health_check()
        assert len(client.calls) == 1
