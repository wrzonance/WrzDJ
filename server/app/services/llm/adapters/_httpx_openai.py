"""Shared httpx-backed OpenAI Chat Completions caller.

Both ``openai_apikey`` (Platform) and ``openai_compatible`` (Hermes/Ollama/etc.)
use the same OpenAI Chat Completions wire format. They differ only in:

- base URL (``https://api.openai.com/v1`` vs the user-supplied URL)
- header (always ``Authorization: Bearer <token>``; bearer is optional for compatible)

This helper handles the actual HTTP call + error mapping. Adapters wrap it with
type-specific credential extraction and registration.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.services.llm.adapters._shared import raise_for_status
from app.services.llm.base import ChatRequest, ChatResponse, ChatResponseChunk, Message
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
from app.services.llm.streaming import parse_openai_stream_event
from app.services.llm.tool_translation import (
    content_to_text,
    parse_openai_response,
    to_openai_tools,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 120.0


def _messages_to_openai(req: ChatRequest) -> list[dict]:
    """Translate canonical messages to OpenAI chat-completions format."""
    out: list[dict] = []
    if req.system:
        out.append({"role": "system", "content": req.system})

    for m in req.messages:
        # OpenAI uses identical role names for system/user/assistant/tool.
        msg: dict[str, Any] = {"role": m.role, "content": content_to_text(m.content)}
        if m.role == "tool":
            if not m.tool_call_id:
                raise ToolTranslationError("Tool result message missing tool_call_id")
            msg["tool_call_id"] = m.tool_call_id
        out.append(msg)
    return out


def _build_payload(req: ChatRequest, model: str | None, *, max_tokens_field: str) -> dict:
    tools, choice = to_openai_tools(req.tools, req.force_tool)

    body: dict[str, Any] = {
        "model": model,
        "messages": _messages_to_openai(req),
    }
    if req.max_tokens is not None:
        body[max_tokens_field] = req.max_tokens
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if tools:
        body["tools"] = tools
    if choice is not None:
        body["tool_choice"] = choice

    return body


async def call_openai_chat(
    *,
    base_url: str,
    api_key: str | None,
    request: ChatRequest,
    fallback_model: str | None,
    extra_headers: dict | None = None,
    max_tokens_field: str = "max_tokens",
) -> ChatResponse:
    """Issue a Chat Completions request and parse the response.

    ``base_url`` must end either at the API root (``/v1``) or at the actual host
    root — this helper appends ``/chat/completions`` and is tolerant of either
    form. Adapters are responsible for ensuring URLs are validated upstream.
    """
    model = request.model or fallback_model
    if not model:
        raise ToolTranslationError(
            "model is required (set ChatRequest.model or LlmConnector.model_hint)"
        )

    endpoint = _build_chat_endpoint(base_url)

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"  # nosec B106
    if extra_headers:
        headers.update(extra_headers)

    timeout = request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    timeout = min(max(timeout, 1.0), MAX_TIMEOUT_SECONDS)

    payload = _build_payload(request, model, max_tokens_field=max_tokens_field)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise ProviderUnavailable("Upstream timeout") from exc
    except httpx.HTTPError as exc:
        raise ProviderUnavailable("Upstream network error") from exc

    raise_for_status(resp)

    try:
        body = resp.json()
    except json.JSONDecodeError as exc:
        raise ToolTranslationError("Upstream returned non-JSON body") from exc
    except ValueError as exc:
        raise ToolTranslationError("Upstream returned non-JSON body") from exc

    return parse_openai_response(body)


def _map_stream_status(status_code: int) -> None:
    """Raise the canonical typed error for a non-2xx streaming status.

    Mirrors ``_shared.raise_for_status`` but operates on a bare status code
    (the streaming path reads the status before consuming the body).
    """
    if status_code in (401, 403):
        raise AuthInvalid(f"Auth failed (HTTP {status_code})")
    if status_code == 402:
        raise QuotaExceeded("Quota or billing failure (HTTP 402)")
    if status_code == 429:
        raise RateLimited("Rate limited (HTTP 429)")
    if 500 <= status_code < 600:
        raise ProviderUnavailable(f"Upstream error (HTTP {status_code})")
    raise ToolTranslationError(f"Upstream rejected request (HTTP {status_code})")


async def stream_openai_chat(
    *,
    base_url: str,
    api_key: str | None,
    request: ChatRequest,
    fallback_model: str | None,
    extra_headers: dict | None = None,
    max_tokens_field: str = "max_tokens",
) -> AsyncIterator[ChatResponseChunk]:
    """Issue a streaming Chat Completions request, yielding canonical chunks.

    Cancellation: if the consumer stops iterating (e.g. an SSE client
    disconnect closes the async generator), the ``async with client.stream(...)``
    context exits and httpx closes the upstream connection, cancelling the
    provider request. Non-2xx statuses are mapped to canonical typed exceptions
    before the first chunk; mid-stream network drops surface as
    ``ProviderUnavailable``.
    """
    model = request.model or fallback_model
    if not model:
        raise ToolTranslationError(
            "model is required (set ChatRequest.model or LlmConnector.model_hint)"
        )

    endpoint = _build_chat_endpoint(base_url)

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"  # nosec B106
    if extra_headers:
        headers.update(extra_headers)

    timeout = request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    timeout = min(max(timeout, 1.0), MAX_TIMEOUT_SECONDS)

    payload = _build_payload(request, model, max_tokens_field=max_tokens_field)
    payload["stream"] = True
    # Ask OpenAI to include token usage in the terminal stream event. Harmless to
    # OpenAI-compatible servers that ignore unknown fields.
    payload["stream_options"] = {"include_usage": True}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", endpoint, json=payload, headers=headers) as resp:
                if resp.status_code >= 300:
                    # Drain the (small) error body so the connection releases,
                    # then map to a typed error. The body is never surfaced.
                    await resp.aread()
                    _map_stream_status(resp.status_code)
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        # Tolerate keepalive / comment frames.
                        continue
                    chunk = parse_openai_stream_event(obj)
                    if chunk is not None:
                        yield chunk
    except httpx.TimeoutException as exc:
        raise ProviderUnavailable("Upstream timeout") from exc
    except httpx.HTTPError as exc:
        raise ProviderUnavailable("Upstream network error") from exc


def _build_chat_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def build_healthcheck_request() -> ChatRequest:
    """Return a minimal request used to verify the connector is alive.

    Deliberately omits ``max_tokens``: reasoning models (OpenAI GPT-5 / o-series)
    spend their completion budget on internal reasoning tokens before producing
    any visible output, so a 1-token cap is fully consumed by reasoning and the
    request fails with HTTP 400 ("max_tokens or model output limit was reached").
    Letting the provider apply its default budget keeps the probe cheap (the
    prompt is trivial) while working for reasoning and non-reasoning models alike.
    Adapters override the ``model`` via the connector's ``model_hint``.
    """
    return ChatRequest(
        messages=[Message(role="user", content="ping")],
        temperature=0.0,
    )
