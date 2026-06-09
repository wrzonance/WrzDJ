"""Shared streaming primitives for LLM adapters.

Holds SSE-line parsing helpers reused by the OpenAI-wire adapters (Platform +
custom OpenAI-compatible). The chunk / delta models themselves live in
``base.py`` alongside ``ChatResponse``.
"""

from __future__ import annotations

from typing import Literal

from app.services.llm.base import ChatResponseChunk, TokenUsage, ToolCallDelta

CanonicalStopReason = Literal["end_turn", "tool_use", "max_tokens", "error"]


def _as_int(value: object, default: int = 0) -> int:
    """Coerce an external (provider-supplied) field to ``int``, tolerantly.

    Streaming payloads come straight off the wire; a non-conforming provider can
    send ``null`` or a non-numeric value for ``index`` / token counts. We never
    want a malformed field to raise and abort an otherwise-usable stream, so fall
    back to ``default`` instead of letting ``int()`` raise.
    """
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
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
    choices = payload.get("choices") or []
    choice = choices[0] if choices else {}
    delta = choice.get("delta") or {}

    text_delta = delta.get("content") or ""

    tool_call_deltas: list[ToolCallDelta] = []
    for tc in delta.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        tool_call_deltas.append(
            ToolCallDelta(
                index=_as_int(tc.get("index", 0)),
                id=tc.get("id"),
                name=fn.get("name"),
                input_json_fragment=fn.get("arguments") or "",
            )
        )

    finish_reason = choice.get("finish_reason")
    done = finish_reason is not None

    stop_reason: CanonicalStopReason | None = None
    if done:
        stop_reason = _FINISH_REASON_OPENAI.get(finish_reason, "error")

    # Usage can arrive on a *separate* terminal frame that carries no text/tool
    # delta and no finish_reason: OpenAI's ``stream_options.include_usage`` emits a
    # final ``choices: []`` event whose only payload is ``usage``. Compute it
    # unconditionally (not just when ``done``) so token accounting survives.
    usage: TokenUsage | None = None
    usage_payload = payload.get("usage") or {}
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
