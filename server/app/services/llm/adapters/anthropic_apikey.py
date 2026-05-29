"""Anthropic API-key adapter — uses the official ``anthropic`` SDK."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from anthropic import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
)

from app.services.llm.adapters._shared import extract_api_key
from app.services.llm.base import (
    ChatRequest,
    ChatResponse,
    ChatResponseChunk,
    LlmAdapter,
    Message,
    TokenUsage,
    ToolCallDelta,
)
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

# Anthropic native stop_reason → canonical. Any other value maps to "end_turn"
# (Anthropic only emits the keys below for completed messages).
_STREAM_FINISH_REASON = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
}


class AnthropicApiKeyAdapter(LlmAdapter):
    connector_type = "anthropic_apikey"

    def _extract_api_key(self) -> str:
        return extract_api_key(self.connector.credentials or "")

    def _client(self, *, timeout: float) -> AsyncAnthropic:
        return AsyncAnthropic(api_key=self._extract_api_key(), timeout=timeout)

    def _resolve_timeout(self, request: ChatRequest) -> float:
        return min(
            max(request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS, 1.0),
            MAX_TIMEOUT_SECONDS,
        )

    def _build_kwargs(self, request: ChatRequest) -> dict[str, Any]:
        """Build the ``messages.create`` / ``messages.stream`` kwargs.

        Shared by ``chat`` and ``stream`` so request translation never drifts
        between the buffered and streamed paths.
        """
        model = request.model or self.connector.model_hint or DEFAULT_MODEL
        max_tokens = request.max_tokens or DEFAULT_MAX_TOKENS

        tools, choice = to_anthropic_tools(request.tools, request.force_tool)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": to_anthropic_messages(request.messages),
        }
        if request.system:
            kwargs["system"] = request.system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if tools:
            kwargs["tools"] = tools
        if choice is not None:
            kwargs["tool_choice"] = choice
        return kwargs

    async def chat(self, request: ChatRequest) -> ChatResponse:
        timeout = self._resolve_timeout(request)
        kwargs = self._build_kwargs(request)

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

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatResponseChunk]:
        timeout = self._resolve_timeout(request)
        kwargs = self._build_kwargs(request)

        # Track whether any tool_use block appeared, plus the terminal
        # stop_reason / output token count gathered from the message_delta event.
        saw_tool_use = False
        stop_reason: str | None = None
        output_tokens: int | None = None

        try:
            async with self._client(timeout=timeout) as client:
                async with client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        chunk, tool_seen, sr, ot = _translate_anthropic_event(event)
                        saw_tool_use = saw_tool_use or tool_seen
                        if sr is not None:
                            stop_reason = sr
                        if ot is not None:
                            output_tokens = ot
                        if chunk is not None:
                            yield chunk
        except APITimeoutError as exc:
            raise ProviderUnavailable("Upstream timeout") from exc
        except APIConnectionError as exc:
            raise ProviderUnavailable("Upstream network error") from exc
        except APIStatusError as exc:
            self._raise_for_status(exc)
        except APIError as exc:
            raise ProviderUnavailable(f"Anthropic API error: {type(exc).__name__}") from exc

        canonical_stop = _STREAM_FINISH_REASON.get(stop_reason or "", "end_turn")
        if saw_tool_use and canonical_stop != "tool_use":
            canonical_stop = "tool_use"
        # Anthropic streams output_tokens in message_delta but input_tokens only
        # in message_start; for the counts-only call log the completion count is
        # what matters, so prompt is recorded as 0 when unavailable.
        final_usage = (
            TokenUsage(prompt=0, completion=output_tokens) if output_tokens is not None else None
        )
        yield ChatResponseChunk(stop_reason=canonical_stop, usage=final_usage, done=True)

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


def _translate_anthropic_event(
    event: Any,
) -> tuple[ChatResponseChunk | None, bool, str | None, int | None]:
    """Translate one Anthropic SDK stream event into stream state.

    Returns ``(chunk_or_None, saw_tool_use, stop_reason_or_None,
    output_tokens_or_None)``. Mirrors the dual dict/object access style of
    ``tool_translation.parse_anthropic_response`` so it tolerates either the
    typed SDK events or plain dicts (used in tests).
    """
    etype = getattr(event, "type", None)

    if etype == "content_block_start":
        block = getattr(event, "content_block", None)
        if getattr(block, "type", None) == "tool_use":
            idx = int(getattr(event, "index", 0))
            chunk = ChatResponseChunk(
                tool_call_deltas=[
                    ToolCallDelta(
                        index=idx,
                        id=getattr(block, "id", None),
                        name=getattr(block, "name", None),
                    )
                ]
            )
            return chunk, True, None, None
        return None, False, None, None

    if etype == "content_block_delta":
        delta = getattr(event, "delta", None)
        dtype = getattr(delta, "type", None)
        if dtype == "text_delta":
            return ChatResponseChunk(text_delta=getattr(delta, "text", "") or ""), False, None, None
        if dtype == "input_json_delta":
            idx = int(getattr(event, "index", 0))
            chunk = ChatResponseChunk(
                tool_call_deltas=[
                    ToolCallDelta(
                        index=idx,
                        input_json_fragment=getattr(delta, "partial_json", "") or "",
                    )
                ]
            )
            return chunk, False, None, None
        return None, False, None, None

    if etype == "message_delta":
        delta = getattr(event, "delta", None)
        stop_reason = getattr(delta, "stop_reason", None)
        usage = getattr(event, "usage", None)
        output_tokens = None
        if usage is not None:
            ot = getattr(usage, "output_tokens", None)
            if ot is not None:
                output_tokens = int(ot)
        return None, False, stop_reason, output_tokens

    return None, False, None, None


register_adapter("anthropic_apikey", AnthropicApiKeyAdapter)
