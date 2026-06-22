"""LLM critique + chat-driven editor tools for WrzDJSet (#390).

Thin orchestration facade over the agent toolkit: builds the chat/critique turn,
dispatches validated tool calls through a closed allowlist, and re-exports the
toolkit's public surface. Tool implementations live in the sibling ``agent_*``
modules (``agent_common``, ``agent_tools_mutations``, ``agent_tools_sensing``,
``agent_tool_specs``, ``agent_display``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.user import User
from app.services.llm.base import ChatRequest, Message
from app.services.llm.exceptions import NoLlmConfigured
from app.services.llm.gateway import Gateway
from app.services.setbuilder.agent_common import (
    MUTATION_TOOLS,
    AgentToolError,
    _ordered_slots,
    _pool_tracks,
)
from app.services.setbuilder.agent_display import _tool_display_summary
from app.services.setbuilder.agent_tool_specs import _agent_tools, _critique_tool
from app.services.setbuilder.agent_tools_mutations import (
    _tool_add_pairing,
    _tool_add_slow_window,
    _tool_apply_curve_template,
    _tool_bump_energy,
    _tool_insert_from_pool,
    _tool_lock_slot,
    _tool_move_range,
    _tool_remove_curve_point,
    _tool_remove_pairing,
    _tool_remove_slot,
    _tool_reorder_slot,
    _tool_replace_slot,
    _tool_search_and_insert,
    _tool_set_curve_point,
    _tool_set_peak_at,
    _tool_set_target,
    _tool_swap_slots,
    _tool_unlock_slot,
)
from app.services.setbuilder.agent_tools_sensing import (
    _explain_warning,
    _tool_analyze_pool_gaps,
    _tool_analyze_transition,
    _tool_explain_transition,
    _tool_get_track_vibes,
    _tool_static_critique,
    _tool_suggest_pairings,
    _tool_summarize_set,
    _track_summary,
)
from app.services.setbuilder.agent_tools_structural import _tool_autobuild
from app.services.setbuilder.pass1_deterministic import (
    TransitionScore,
    recompute_transition_scores,
)
from app.services.setbuilder.pass1_deterministic import _track_meta as _pass1_track_meta

logger = logging.getLogger(__name__)

# Public surface re-exported for routes + tests, which import these from this
# module and monkeypatch ``pass2_agent.Gateway.dispatch``. Listing the names
# that are not referenced inside this module (sensing helpers used only by
# tests) keeps ruff from dropping the re-exports.
__all__ = [
    "AgentChatResult",
    "AgentToolError",
    "AppliedToolCall",
    "CritiqueFlag",
    "CritiqueFlagType",
    "Gateway",
    "MUTATION_TOOLS",
    "SetCritique",
    "_agent_tools",
    "_explain_warning",
    "_set_context",
    "_tool_display_summary",
    "_track_summary",
    "apply_tool_call",
    "chat_with_agent",
    "critique_set",
]


CritiqueFlagType = Literal[
    "energy_dip",
    "vibe_clash",
    "era_jump",
    "sing_along_missing",
    "banger_buried",
    "transition_brilliant",
]


ALLOWED_FLAG_TYPES = {
    "energy_dip",
    "vibe_clash",
    "era_jump",
    "sing_along_missing",
    "banger_buried",
    "transition_brilliant",
}


@dataclass(frozen=True)
class CritiqueFlag:
    type: CritiqueFlagType
    slot_position: int | None = None
    message: str | None = None


@dataclass(frozen=True)
class SetCritique:
    overall_grade: str
    summary: str
    flags: list[CritiqueFlag] = field(default_factory=list)


@dataclass(frozen=True)
class AppliedToolCall:
    id: str
    name: str
    args: dict[str, Any]
    rationale: str | None
    result: dict[str, Any]
    mutating: bool
    display_summary: str


@dataclass(frozen=True)
class AgentChatResult:
    message: str
    tool_calls: list[AppliedToolCall]
    slots: list[SetSlot]
    affected_transition_scores: list[TransitionScore]


async def critique_set(db: Session, actor: User, set_obj: Set) -> SetCritique:
    """Ask the gateway for a structured set critique."""
    response = await Gateway.dispatch(
        db,
        actor,
        ChatRequest(
            system=(
                "You are WrzDJSet's strong critique pass. Return only the critique_set tool "
                "with a concise grade and flags."
            ),
            messages=[Message(role="user", content=_set_context(db, set_obj))],
            tools=[_critique_tool()],
            force_tool="critique_set",
            temperature=0.2,
            max_tokens=900,
            # The product concept calls this the "strong" pass. Gateway v1 has
            # connector model hints, not speed tiers, so we leave the configured
            # model in control instead of overriding it with a non-model label.
            model=None,
        ),
        purpose="set_builder",
    )
    payload: dict[str, Any] = {}
    if response.tool_calls:
        payload = response.tool_calls[0].input
    elif response.text:
        payload = json.loads(response.text)
    return _critique_from_payload(payload)


async def _chat_critique_result(
    db: Session, actor: User, set_obj: Set, payload: dict[str, Any]
) -> dict[str, Any]:
    """Resolve an in-chat ``critique_set`` call to the strong LLM critique.

    Falls back to the deterministic static critique when no connector is
    configured, so a chat turn degrades gracefully instead of hard-failing.
    """
    try:
        critique = await critique_set(db, actor, set_obj)
    except NoLlmConfigured:
        logger.info("Set %s chat critique: no LLM connector, using static fallback", set_obj.id)
        static_result, _ = _tool_static_critique(db, set_obj, payload)
        return {**static_result, "available": False}
    logger.debug("Set %s chat critique: used strong LLM pass", set_obj.id)
    return {
        "available": True,
        "overall_grade": critique.overall_grade,
        "summary": critique.summary,
        "flags": [
            {"type": flag.type, "slot_position": flag.slot_position, "message": flag.message}
            for flag in critique.flags
        ],
    }


async def chat_with_agent(
    db: Session,
    actor: User,
    set_obj: Set,
    *,
    message: str,
    history: list[dict[str, str]] | None = None,
    messages: list[Message] | None = None,
    commit: bool = True,
) -> AgentChatResult:
    """Run one chat turn and apply any requested setbuilder tools."""
    if messages is None:
        messages = [Message(role="user", content=_set_context(db, set_obj))]
        for item in history or []:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and content:
                messages.append(Message(role=role, content=content))
        messages.append(Message(role="user", content=message))

    response = await Gateway.dispatch(
        db,
        actor,
        ChatRequest(
            system=(
                "You are WrzDJSet's fast editing agent. Use tools for concrete edits. "
                "Every mutating tool input must include rationale."
            ),
            messages=messages,
            tools=_agent_tools(),
            temperature=0.3,
            max_tokens=1200,
            # Conceptually this is the "fast" chat/editor turn. Do not override
            # the connector's configured model until the gateway grows tiers.
            model=None,
        ),
        purpose="set_builder",
    )
    applied: list[AppliedToolCall] = []
    affected: set[int] = set()
    critique_result: dict[str, Any] | None = None
    try:
        for call in response.tool_calls:
            before = _slot_snapshots(db, set_obj)
            if call.name == "critique_set":
                # Run the strong LLM critique once per turn; reuse it for
                # duplicate calls so a chat turn never doubles the dispatch.
                if critique_result is None:
                    critique_result = await _chat_critique_result(db, actor, set_obj, call.input)
                result, positions = critique_result, set()
            else:
                result, positions = apply_tool_call(db, set_obj, call.name, call.input)
            after = _slot_snapshots(db, set_obj)
            mutating = call.name in MUTATION_TOOLS
            summary = _tool_display_summary(call.name, call.input, result, before, after)
            applied.append(
                AppliedToolCall(
                    id=call.id,
                    name=call.name,
                    args=call.input,
                    rationale=call.input.get("rationale"),
                    result=result,
                    mutating=mutating,
                    display_summary=summary,
                )
            )
            affected.update(positions)

        message = response.text or ""
        if not message.strip() and applied:
            message = " ".join(tool.display_summary for tool in applied)

        slots = _ordered_slots(db, set_obj.id)
        transition_scores: list[TransitionScore] = []
        if affected:
            affected_with_neighbors = _with_neighbors(affected)
            transition_scores = recompute_transition_scores(
                db, set_obj, slots, affected_with_neighbors, commit=False
            )
    except Exception:
        if commit:
            db.rollback()
        raise
    if commit:
        db.commit()
    return AgentChatResult(
        message=message,
        tool_calls=applied,
        slots=slots,
        affected_transition_scores=transition_scores,
    )


def apply_tool_call(
    db: Session,
    set_obj: Set,
    name: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], set[int]]:
    """Apply a validated tool call and return a small result + affected positions."""
    if name in MUTATION_TOOLS and not str(payload.get("rationale") or "").strip():
        raise AgentToolError(f"{name} requires a rationale")
    handlers = {
        "reorder_slot": _tool_reorder_slot,
        "move_range": _tool_move_range,
        "swap_slots": _tool_swap_slots,
        "remove_slot": _tool_remove_slot,
        "replace_slot": _tool_replace_slot,
        "insert_from_pool": _tool_insert_from_pool,
        "search_and_insert": _tool_search_and_insert,
        "add_slow_window": _tool_add_slow_window,
        "set_peak_at": _tool_set_peak_at,
        "bump_energy": _tool_bump_energy,
        "set_curve_point": _tool_set_curve_point,
        "remove_curve_point": _tool_remove_curve_point,
        "apply_curve_template": _tool_apply_curve_template,
        "autobuild": _tool_autobuild,
        "set_target": _tool_set_target,
        "lock_slot": _tool_lock_slot,
        "unlock_slot": _tool_unlock_slot,
        "add_pairing": _tool_add_pairing,
        "remove_pairing": _tool_remove_pairing,
        "analyze_transition": _tool_analyze_transition,
        "explain_transition": _tool_explain_transition,
        "get_track_vibes": _tool_get_track_vibes,
        "summarize_set": _tool_summarize_set,
        "analyze_pool_gaps": _tool_analyze_pool_gaps,
        "suggest_pairings": _tool_suggest_pairings,
        "critique_set": _tool_static_critique,
    }
    handler = handlers.get(name)
    if handler is None:
        raise AgentToolError(f"Unknown tool: {name}")
    mutating = name in MUTATION_TOOLS
    # Single audit point for every agent tool action: logging here, at the
    # dispatch choke point, covers all handlers (mutating + read-only) without
    # duplicating log calls across each one. State changes log at INFO.
    logger.log(
        logging.INFO if mutating else logging.DEBUG,
        "setbuilder agent tool %s applied to set %s (mutating=%s)",
        name,
        set_obj.id,
        mutating,
    )
    return handler(db, set_obj, payload)


def _with_neighbors(positions: set[int]) -> set[int]:
    expanded = set()
    for pos in positions:
        expanded.update({pos - 1, pos, pos + 1})
    return {p for p in expanded if p >= 0}


def _critique_from_payload(payload: dict[str, Any]) -> SetCritique:
    flags = []
    for item in payload.get("flags", []):
        flag_type = item.get("type")
        if flag_type in ALLOWED_FLAG_TYPES:
            flags.append(
                CritiqueFlag(
                    type=flag_type,
                    slot_position=item.get("slot_position"),
                    message=item.get("message"),
                )
            )
    return SetCritique(
        overall_grade=str(payload.get("overall_grade") or "C"),
        summary=str(payload.get("summary") or ""),
        flags=flags,
    )


def _set_context(db: Session, set_obj: Set) -> str:
    slots = _ordered_slots(db, set_obj.id)
    tracks = {_pass1_track_meta(t).slot_track_id: t for t in _pool_tracks(db, set_obj.id)}
    rows = []
    for slot in slots:
        track = tracks.get(slot.track_id or "")
        rows.append(
            {
                "position": slot.position,
                "slot_id": slot.id,
                "locked": slot.locked,
                "target_energy": slot.target_energy,
                "transition_score": slot.transition_score,
                "track": (
                    {
                        "pool_track_id": track.id,
                        "title": track.title,
                        "artist": track.artist,
                        "bpm": track.bpm,
                        "key": track.camelot or track.key,
                        "energy": track.energy,
                    }
                    if track
                    else None
                ),
            }
        )
    return json.dumps(
        {
            "set_id": set_obj.id,
            "name": set_obj.name,
            "key_strictness": set_obj.key_strictness,
            "slots": rows,
        },
        separators=(",", ":"),
    )


def _slot_snapshots(db: Session, set_obj: Set) -> dict[int, dict[str, Any]]:
    tracks = {_pass1_track_meta(t).slot_track_id: t for t in _pool_tracks(db, set_obj.id)}
    snapshots: dict[int, dict[str, Any]] = {}
    for slot in _ordered_slots(db, set_obj.id):
        track = tracks.get(slot.track_id or "")
        title = track.title if track else f"slot {slot.position + 1}"
        artist = track.artist if track else None
        label = f"{title} - {artist}" if artist else title
        snapshots[slot.id] = {
            "slot_id": slot.id,
            "position": slot.position,
            "track_id": slot.track_id,
            "label": label,
            "target_energy": slot.target_energy,
        }
    return snapshots
