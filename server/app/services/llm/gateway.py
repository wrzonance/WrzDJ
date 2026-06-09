"""Provider-agnostic LLM gateway (Phase 0 interface stub).

This is the single call surface WrzDJSet codes against. The real gateway
(OAuth multi-provider dispatch) ships in a parallel worktree; until it merges
this stub delegates to the existing Anthropic path in
``services/recommendation/llm_client.py``. Per exec-summary 6/9 ("slip
insurance"), WrzDJSet is NOT blocked on the gateway merge.

CRITICAL: no provider SDK is imported here. Model identifiers are plain
strings resolved from a ``model_hint``. The actual provider call is isolated in
``_raw_provider_call``, which delegates to the existing recommendation LLM
client; the ``anthropic`` import lives only in that client module, never here.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

ModelHint = Literal["fast", "strong"]
MODEL_HINTS: tuple[str, ...] = ("fast", "strong")


@dataclass
class GatewayResponse:
    """Normalized LLM response: tool calls + free text, provider-agnostic."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""


def _resolve_model(model_hint: ModelHint) -> str:
    """Map a coarse capability hint to a concrete model string.

    Reads the configured Anthropic model for the temporary delegating impl.
    When the OAuth gateway lands this becomes a provider-aware lookup driven
    by SystemSettings; the hint contract ("fast" vs "strong") stays stable.
    """
    from app.core.config import get_settings

    settings = get_settings()
    # Phase 0: single-provider delegation. Both hints resolve to the
    # configured model; the gateway epic differentiates fast/strong tiers.
    return settings.anthropic_model


async def _raw_provider_call(
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> Any:
    """Isolated provider call. Delegates to the existing recommendation client.

    The provider SDK import lives ONLY in services/recommendation/llm_client.py.
    This module never imports a provider SDK (enforced by test).
    """
    from app.services.recommendation import llm_client

    return await llm_client.raw_messages_create(
        model=model,
        system=system,
        tools=tools,
        tool_choice=tool_choice,
        messages=messages,
        max_tokens=max_tokens,
    )


def _normalize(response: Any) -> GatewayResponse:
    """Translate a provider response into the normalized GatewayResponse."""
    text = ""
    tool_calls: list[dict[str, Any]] = []
    for block in getattr(response, "content", []) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            text += getattr(block, "text", "")
        elif btype == "tool_use":
            tool_calls.append(
                {"name": getattr(block, "name", ""), "input": getattr(block, "input", {})}
            )
    return GatewayResponse(tool_calls=tool_calls, text=text)


async def dispatch(
    *,
    messages: list[dict[str, Any]],
    tool: dict[str, Any] | None = None,
    system: str = "",
    model_hint: ModelHint = "fast",
    max_tokens: int = 2048,
) -> GatewayResponse:
    """Dispatch a single LLM turn and return a normalized response.

    Args:
        messages: provider-agnostic message list ([{"role", "content"}]).
        tool: a single JSONSchema tool spec ({"name", "input_schema"});
            when provided, the gateway forces tool use.
        system: optional system prompt.
        model_hint: "fast" (batch/chat) or "strong" (critique/grading).
        max_tokens: response token cap.

    Returns:
        GatewayResponse with ``tool_calls`` and ``text``.
    """
    model = _resolve_model(model_hint)
    tools = [tool] if tool else []
    tool_choice = {"type": "tool", "name": tool["name"]} if tool else None
    response = await _raw_provider_call(
        model=model,
        system=system,
        tools=tools,
        tool_choice=tool_choice,
        messages=messages,
        max_tokens=max_tokens,
    )
    return _normalize(response)
