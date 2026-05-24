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
from typing import Any

import httpx

from app.services.llm.base import ChatRequest, ChatResponse, Message
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
from app.services.llm.tool_translation import parse_openai_response, to_openai_tools

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 120.0


def _messages_to_openai(req: ChatRequest) -> list[dict]:
    """Translate canonical messages to OpenAI chat-completions format."""
    out: list[dict] = []
    if req.system:
        out.append({"role": "system", "content": req.system})

    for m in req.messages:
        content = m.content
        if isinstance(content, list):
            # Concatenate text blocks — MVP is text-only.
            text = "".join(getattr(b, "text", "") or "" for b in content)
        else:
            text = content or ""

        msg: dict[str, Any] = {"role": _normalise_role(m.role), "content": text}
        if m.role == "tool":
            if not m.tool_call_id:
                raise ToolTranslationError("Tool result message missing tool_call_id")
            msg["tool_call_id"] = m.tool_call_id
        out.append(msg)
    return out


def _normalise_role(role: str) -> str:
    # OpenAI uses identical role names for system/user/assistant/tool.
    return role


def _build_payload(req: ChatRequest, model: str | None) -> dict:
    tools, choice = to_openai_tools(req.tools, req.force_tool)

    body: dict[str, Any] = {
        "model": model,
        "messages": _messages_to_openai(req),
    }
    if req.max_tokens is not None:
        body["max_tokens"] = req.max_tokens
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

    payload = _build_payload(request, model)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise ProviderUnavailable("Upstream timeout") from exc
    except httpx.HTTPError as exc:
        raise ProviderUnavailable("Upstream network error") from exc

    _raise_for_status(resp)

    try:
        body = resp.json()
    except json.JSONDecodeError as exc:
        raise ToolTranslationError("Upstream returned non-JSON body") from exc
    except ValueError as exc:
        raise ToolTranslationError("Upstream returned non-JSON body") from exc

    return parse_openai_response(body)


def _build_chat_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _raise_for_status(resp: httpx.Response) -> None:
    if 200 <= resp.status_code < 300:
        return

    code = resp.status_code
    if code in (401, 403):
        raise AuthInvalid(f"Auth failed (HTTP {code})")
    if code == 402:
        raise QuotaExceeded("Quota or billing failure (HTTP 402)")
    if code == 429:
        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
        raise RateLimited("Rate limited (HTTP 429)", retry_after_seconds=retry_after)
    if 500 <= code < 600:
        raise ProviderUnavailable(f"Upstream error (HTTP {code})")
    # 4xx other than the above → treat as a malformed input / translation error
    # since the gateway only emits known shapes.
    raise ToolTranslationError(f"Upstream rejected request (HTTP {code})")


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def build_healthcheck_request() -> ChatRequest:
    """Return a minimal request used to verify the connector is alive.

    A 1-token call is cheap and exercises the auth path. Adapters override the
    ``model`` via the connector's ``model_hint`` before sending.
    """
    return ChatRequest(
        messages=[Message(role="user", content="ping")],
        max_tokens=1,
        temperature=0.0,
    )
