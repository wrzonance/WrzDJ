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
            if not name or not tool_id:
                raise ToolTranslationError("Anthropic tool_use block missing id/name")
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


# ---------------------------------------------------------------------------
# Bedrock — Llama family
#
# Llama models on Bedrock (meta.llama*) have no structured tool/function field
# in the InvokeModel request. The convention (matching Meta's tool-use prompt
# format) is to describe the available tools inside the system prompt and ask
# the model to emit a single JSON object as its reply. We then parse that JSON
# back into a canonical ``ToolCall``.
# ---------------------------------------------------------------------------
def render_llama_tool_instructions(tools: list[ToolSpec] | None, force: str | None) -> str | None:
    """Build a system-prompt fragment describing the available tools.

    Returns ``None`` when there are no tools. When ``force`` is set, the
    fragment instructs the model to call exactly that tool.
    """
    if not tools:
        return None
    if force is not None and not any(t.name == force for t in tools):
        raise ToolTranslationError(f"force_tool={force!r} not in tools list")

    lines = [
        "You have access to the following tools. To call a tool, respond with "
        "ONLY a single JSON object and no other text, of the form: "
        '{"name": "<tool_name>", "input": {<arguments>}}.',
    ]
    for t in tools:
        lines.append(
            f"- {t.name}: {t.description} "
            f"(input JSON schema: {json.dumps(t.input_schema, sort_keys=True)})"
        )
    if force is not None:
        lines.append(f"You MUST call the tool named {force!r}.")
    return "\n".join(lines)


def parse_llama_response(payload: dict, tool_names: set[str] | None = None) -> ChatResponse:
    """Parse a Bedrock Llama InvokeModel response body.

    Bedrock Llama returns ``{"generation": "...", "stop_reason": "stop|length",
    "prompt_token_count": int, "generation_token_count": int}``. When the
    generated text is a tool-call JSON object whose ``name`` is one of the
    expected tools, surface it as a ``ToolCall``.
    """
    if not isinstance(payload, dict):
        raise ToolTranslationError("Bedrock Llama response is not a JSON object")

    generation = payload.get("generation")
    if generation is None:
        raise ToolTranslationError("Bedrock Llama response missing 'generation'")
    text = str(generation)

    stop_reason = _normalise_llama_stop_reason(payload.get("stop_reason"))

    usage = None
    prompt_tokens = payload.get("prompt_token_count")
    completion_tokens = payload.get("generation_token_count")
    if prompt_tokens is not None and completion_tokens is not None:
        usage = TokenUsage(prompt=int(prompt_tokens), completion=int(completion_tokens))

    tool_calls: list[ToolCall] = []
    parsed = _try_parse_tool_json(text)
    if parsed is not None:
        name = parsed.get("name")
        tool_input = parsed.get("input")
        if (
            isinstance(name, str)
            and name
            and isinstance(tool_input, dict)
            and (tool_names is None or name in tool_names)
        ):
            tool_calls.append(ToolCall(id=name, name=name, input=tool_input))
            stop_reason = "tool_use"
            text = ""

    return ChatResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        usage=usage,
        model=None,
    )


def _try_parse_tool_json(text: str) -> dict | None:
    """Best-effort extraction of a single ``{"name":..., "input":...}`` object.

    Llama sometimes wraps the JSON in prose or code fences; we extract the first
    balanced ``{...}`` span and attempt to decode it.
    """
    candidate = text.strip()
    if not candidate:
        return None
    # Strip ``` fences if present.
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        # drop a leading "json" language tag
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
        candidate = candidate.strip()

    start = candidate.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = candidate[start : i + 1]
                try:
                    obj = json.loads(blob)
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def _normalise_llama_stop_reason(
    reason: str | None,
) -> Literal["end_turn", "tool_use", "max_tokens", "error"]:
    if reason in (None, "stop"):
        return "end_turn"
    if reason == "length":
        return "max_tokens"
    return "error"
