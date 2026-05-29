"""Anthropic API-key adapter — uses the official ``anthropic`` SDK."""

from __future__ import annotations

import logging
from typing import Any

from anthropic import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
)

from app.services.llm.adapters._shared import extract_api_key
from app.services.llm.base import ChatRequest, ChatResponse, LlmAdapter, Message
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
from app.services.llm.registry import register_adapter
from app.services.llm.tool_translation import (
    parse_anthropic_response,
    to_anthropic_messages,
    to_anthropic_tools,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 120.0


class AnthropicApiKeyAdapter(LlmAdapter):
    connector_type = "anthropic_apikey"

    def _extract_api_key(self) -> str:
        return extract_api_key(self.connector.credentials or "")

    def _client(self, *, timeout: float) -> AsyncAnthropic:
        return AsyncAnthropic(api_key=self._extract_api_key(), timeout=timeout)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self.connector.model_hint or DEFAULT_MODEL
        max_tokens = request.max_tokens or DEFAULT_MAX_TOKENS
        timeout = min(
            max(request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS, 1.0),
            MAX_TIMEOUT_SECONDS,
        )

        anthropic_messages = to_anthropic_messages(request.messages)
        tools, choice = to_anthropic_tools(request.tools, request.force_tool)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }
        if request.system:
            kwargs["system"] = request.system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if tools:
            kwargs["tools"] = tools
        if choice is not None:
            kwargs["tool_choice"] = choice

        async with self._client(timeout=timeout) as client:
            try:
                message = await client.messages.create(**kwargs)
            except APITimeoutError as exc:
                raise ProviderUnavailable("Upstream timeout") from exc
            except APIConnectionError as exc:
                raise ProviderUnavailable("Upstream network error") from exc
            except APIStatusError as exc:
                self._raise_for_status(exc)
            except APIError as exc:
                raise ProviderUnavailable(f"Anthropic API error: {type(exc).__name__}") from exc

        return parse_anthropic_response(message)

    async def health_check(self) -> None:
        # 1-token ping to validate the key + reach the API.
        ping = ChatRequest(
            messages=[Message(role="user", content="ping")],
            max_tokens=1,
            temperature=0.0,
        )
        await self.chat(ping)

    @staticmethod
    def _raise_for_status(exc: APIStatusError) -> None:
        status = getattr(exc, "status_code", None)
        if status in (401, 403):
            raise AuthInvalid(f"Auth failed (HTTP {status})") from exc
        if status == 402:
            raise QuotaExceeded("Quota or billing failure (HTTP 402)") from exc
        if status == 429:
            retry_after = None
            try:
                resp_headers = getattr(exc.response, "headers", {}) or {}
                retry_after_raw = resp_headers.get("retry-after") or resp_headers.get("Retry-After")
                if retry_after_raw:
                    retry_after = int(float(retry_after_raw))
            except (TypeError, ValueError, AttributeError):
                retry_after = None
            raise RateLimited("Rate limited (HTTP 429)", retry_after_seconds=retry_after) from exc
        if status is not None and 500 <= status < 600:
            raise ProviderUnavailable(f"Upstream error (HTTP {status})") from exc
        raise ToolTranslationError(f"Upstream rejected request (HTTP {status})") from exc


register_adapter("anthropic_apikey", AnthropicApiKeyAdapter)
