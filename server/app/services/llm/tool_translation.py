"""Translate canonical ``ToolSpec`` → per-provider tool/function shape.

Each translation helper returns a tuple ``(tools_list, tool_choice_or_none)``
ready to drop into the provider's request body.

Also exposes response parsers that convert provider-native message shapes
back into canonical ``ChatResponse`` (with ``tool_calls``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from app.services.llm.base import ChatResponse, TokenUsage, ToolCall, ToolSpec
from app.services.llm.exceptions import ToolTranslationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
def to_openai_tools(
    tools: list[ToolSpec] | None, force: str | None
) -> tuple[list[dict] | None, Any]:
    if not tools:
        return None, None
    fns = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]
    choice: Any = None
    if force is not None:
        if not any(t.name == force for t in tools):
            raise ToolTranslationError(f"force_tool={force!r} not in tools list")
        choice = {"type": "function", "function": {"name": force}}
    return fns, choice


def parse_openai_response(payload: dict) -> ChatResponse:
    """Parse an OpenAI chat-completions response body."""
    try:
        choice = payload["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ToolTranslationError("OpenAI response missing choices/message") from exc

    text = msg.get("content") or ""

    tool_calls: list[ToolCall] = []
    raw_tool_calls = msg.get("tool_calls") or []
    for tc in raw_tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name") or tc.get("name") or ""
        raw_args = fn.get("arguments")
        try:
            input_obj = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except json.JSONDecodeError as exc:
            raise ToolTranslationError("OpenAI tool_call arguments are not valid JSON") from exc
        tool_calls.append(ToolCall(id=str(tc.get("id") or name), name=name, input=input_obj))

    stop_reason = _normalise_openai_finish_reason(choice.get("finish_reason"))
    usage_payload = payload.get("usage") or {}
    usage = None
    if usage_payload:
        usage = TokenUsage(
            prompt=int(usage_payload.get("prompt_tokens", 0)),
            completion=int(usage_payload.get("completion_tokens", 0)),
        )

    # If the model used tool_calls, force-set stop_reason to tool_use even if
    # finish_reason reported "stop" (some compatible servers do).
    if tool_calls and stop_reason != "tool_use":
        stop_reason = "tool_use"

    return ChatResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        usage=usage,
        model=payload.get("model"),
    )


def _normalise_openai_finish_reason(
    reason: str | None,
) -> Literal["end_turn", "tool_use", "max_tokens", "error"]:
    if reason in (None, "stop"):
        return "end_turn"
    if reason == "tool_calls" or reason == "function_call":
        return "tool_use"
    if reason == "length":
        return "max_tokens"
    return "error"


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
def to_anthropic_tools(
    tools: list[ToolSpec] | None, force: str | None
) -> tuple[list[dict] | None, Any]:
    if not tools:
        return None, None
    anthropic_tools = [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]
    choice: Any = None
    if force is not None:
        if not any(t.name == force for t in tools):
            raise ToolTranslationError(f"force_tool={force!r} not in tools list")
        choice = {"type": "tool", "name": force}
    return anthropic_tools, choice


def parse_anthropic_response(message: Any) -> ChatResponse:
    """Parse the official ``anthropic`` SDK Message object."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    if isinstance(message, dict):
        content_blocks = message.get("content") or []
    else:
        content_blocks = getattr(message, "content", None) or []
    for block in content_blocks:
        if isinstance(block, dict):
            btype = block.get("type")
        else:
            btype = getattr(block, "type", None)
        if btype == "text":
            if isinstance(block, dict):
                text = block.get("text") or ""
            else:
                text = getattr(block, "text", "") or ""
            text_parts.append(text)
        elif btype == "tool_use":
            if isinstance(block, dict):
                name = block.get("name")
                tool_id = block.get("id") or name
                input_obj = block.get("input")
            else:
                name = getattr(block, "name", None)
                tool_id = getattr(block, "id", None) or name
                input_obj = getattr(block, "input", None)
            tool_calls.append(
                ToolCall(id=str(tool_id), name=str(name), input=dict(input_obj or {}))
            )

    stop_raw = getattr(message, "stop_reason", None) or (
        message.get("stop_reason") if isinstance(message, dict) else None
    )
    stop_reason = _normalise_anthropic_stop_reason(stop_raw)
    if tool_calls and stop_reason != "tool_use":
        stop_reason = "tool_use"

    usage_obj = getattr(message, "usage", None) or (
        message.get("usage") if isinstance(message, dict) else None
    )
    usage = None
    if usage_obj is not None:
        prompt = (
            getattr(usage_obj, "input_tokens", None)
            if not isinstance(usage_obj, dict)
            else usage_obj.get("input_tokens")
        )
        completion = (
            getattr(usage_obj, "output_tokens", None)
            if not isinstance(usage_obj, dict)
            else usage_obj.get("output_tokens")
        )
        if prompt is not None and completion is not None:
            usage = TokenUsage(prompt=int(prompt), completion=int(completion))

    model = getattr(message, "model", None) or (
        message.get("model") if isinstance(message, dict) else None
    )

    return ChatResponse(
        text="".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        usage=usage,
        model=model,
    )


def _normalise_anthropic_stop_reason(
    reason: str | None,
) -> Literal["end_turn", "tool_use", "max_tokens", "error"]:
    if reason in (None, "end_turn", "stop_sequence"):
        return "end_turn"
    if reason == "tool_use":
        return "tool_use"
    if reason == "max_tokens":
        return "max_tokens"
    return "error"
