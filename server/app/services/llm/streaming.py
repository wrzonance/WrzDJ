"""Shared streaming primitives for LLM adapters.

Holds SSE-line parsing helpers reused by the OpenAI-wire adapters (Platform +
custom OpenAI-compatible). The chunk / delta models themselves live in
``base.py`` alongside ``ChatResponse``.
"""

from __future__ import annotations

from app.services.llm.base import (
    CanonicalStopReason,
    ChatResponseChunk,
    TokenUsage,
    ToolCallDelta,
)
from app.services.llm.exceptions import ToolTranslationError


def _as_int(value: object, default: int = 0) -> int:
    """Coerce an external (provider-supplied) field to ``int``, tolerantly.

    Streaming payloads come straight off the wire; a non-conforming provider can
    send ``null`` or a non-numeric value for ``index`` / token counts. We never
    want a malformed field to raise and abort an otherwise-usable stream, so fall
    back to ``default`` instead of letting ``int()`` raise.
    """
    # JSON values can only be strings or numbers here; other provider values
    # (including null, lists, and objects) are malformed and use the default.
    if not isinstance(value, (str, int, float)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


# OpenAI streaming finish_reason → canonical stop_reason. Mirrors the
# non-streaming mapping in ``tool_translation._FINISH_REASON_OPENAI``; kept local
# so this module owns no private cross-module imports. Any reason absent from the
# table maps to "error".
_FINISH_REASON_OPENAI: dict[str, CanonicalStopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
}


def parse_openai_stream_event(payload: dict) -> ChatResponseChunk | None:
    """Translate one parsed OpenAI streaming JSON object into a chunk.

    Returns ``None`` for payloads carrying no usable signal (e.g. the initial
    role-only delta). The terminal event (``finish_reason`` set) returns a chunk
    with ``done=True``, the mapped ``stop_reason`` and (when present) token usage.
    """
    if not isinstance(payload, dict):
        raise ToolTranslationError("Upstream returned malformed streaming data")

    choices = payload.get("choices") or []
    if not isinstance(choices, list):
        raise ToolTranslationError("Upstream returned malformed streaming data")
    choice = choices[0] if choices else {}
    if not isinstance(choice, dict):
        raise ToolTranslationError("Upstream returned malformed streaming data")
    delta = choice.get("delta") or {}
    if not isinstance(delta, dict):
        raise ToolTranslationError("Upstream returned malformed streaming data")

    text_delta = delta.get("content") or ""

    tool_calls = delta.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        raise ToolTranslationError("Upstream returned malformed streaming data")

    tool_call_deltas: list[ToolCallDelta] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        fn: dict = {}
        function_payload = tc.get("function")
        if isinstance(function_payload, dict):
            fn = function_payload
        tool_call_deltas.append(
            ToolCallDelta(
                index=_as_int(tc.get("index", 0)),
                id=tc.get("id"),
                name=fn.get("name"),
                input_json_fragment=fn.get("arguments") or "",
            )
        )

    finish_reason = choice.get("finish_reason")
    if finish_reason is None:
        done = False
    elif isinstance(finish_reason, str):
        done = True
    else:
        raise ToolTranslationError("Upstream returned malformed streaming data")

    stop_reason: CanonicalStopReason | None = None
    if isinstance(finish_reason, str):
        stop_reason = _FINISH_REASON_OPENAI.get(finish_reason, "error")

    # Usage can arrive on a *separate* terminal frame that carries no text/tool
    # delta and no finish_reason: OpenAI's ``stream_options.include_usage`` emits a
    # final ``choices: []`` event whose only payload is ``usage``. Compute it
    # unconditionally (not just when ``done``) so token accounting survives.
    usage: TokenUsage | None = None
    usage_payload = payload.get("usage") or {}
    if not isinstance(usage_payload, dict):
        raise ToolTranslationError("Upstream returned malformed streaming data")
    if usage_payload:
        usage = TokenUsage(
            prompt=_as_int(usage_payload.get("prompt_tokens", 0)),
            completion=_as_int(usage_payload.get("completion_tokens", 0)),
        )

    if not text_delta and not tool_call_deltas and not done and usage is None:
        return None

    return ChatResponseChunk(
        text_delta=text_delta,
        tool_call_deltas=tool_call_deltas,
        stop_reason=stop_reason,
        usage=usage,
        done=done,
    )
