"""LLM critique + chat-driven editor tools for WrzDJSet (#390)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolTrack
from app.models.user import User
from app.services.llm.base import ChatRequest, Message, ToolSpec
from app.services.llm.exceptions import NoLlmConfigured
from app.services.llm.gateway import Gateway
from app.services.recommendation.camelot import parse_key
from app.services.setbuilder import curve
from app.services.setbuilder.pass1_deterministic import (
    TransitionScore,
    recompute_transition_scores,
    transition_score,
)
from app.services.setbuilder.pass1_deterministic import _track_meta as _pass1_track_meta

logger = logging.getLogger(__name__)

CritiqueFlagType = Literal[
    "energy_dip",
    "vibe_clash",
    "era_jump",
    "sing_along_missing",
    "banger_buried",
    "transition_brilliant",
]

MUTATION_TOOLS = {
    "reorder_slot",
    "swap_slots",
    "remove_slot",
    "insert_from_pool",
    "search_and_insert",
    "add_slow_window",
    "set_peak_at",
    "bump_energy",
}
ALLOWED_FLAG_TYPES = {
    "energy_dip",
    "vibe_clash",
    "era_jump",
    "sing_along_missing",
    "banger_buried",
    "transition_brilliant",
}


class AgentToolError(ValueError):
    """The model requested an invalid or unsafe setbuilder tool operation."""


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
        "swap_slots": _tool_swap_slots,
        "remove_slot": _tool_remove_slot,
        "insert_from_pool": _tool_insert_from_pool,
        "search_and_insert": _tool_search_and_insert,
        "add_slow_window": _tool_add_slow_window,
        "set_peak_at": _tool_set_peak_at,
        "bump_energy": _tool_bump_energy,
        "analyze_transition": _tool_analyze_transition,
        "summarize_set": _tool_summarize_set,
        "critique_set": _tool_static_critique,
    }
    handler = handlers.get(name)
    if handler is None:
        raise AgentToolError(f"Unknown tool: {name}")
    return handler(db, set_obj, payload)


def _tool_reorder_slot(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    slot = _slot_or_error(db, set_obj.id, int(payload["slot_id"]))
    new_position = int(payload["position"])
    if slot.locked:
        raise AgentToolError("Locked slots cannot be moved")
    slots = _ordered_slots(db, set_obj.id)
    max_pos = max(0, len(slots) - 1)
    new_position = max(0, min(max_pos, new_position))
    old_position = slot.position
    low, high = sorted([old_position, new_position])
    if any(s.locked and s.id != slot.id and low <= s.position <= high for s in slots):
        raise AgentToolError("Reorder would move a locked slot")
    moving = [s for s in slots if s.id == slot.id][0]
    remaining = [s for s in slots if s.id != slot.id]
    remaining.insert(new_position, moving)
    for idx, row in enumerate(remaining):
        row.position = idx
    db.flush()
    return {"slot_id": slot.id, "position": new_position}, set(range(low, high + 1))


def _tool_swap_slots(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    a = _slot_or_error(db, set_obj.id, int(payload["slot_a_id"]))
    b = _slot_or_error(db, set_obj.id, int(payload["slot_b_id"]))
    if a.locked or b.locked:
        raise AgentToolError("Locked slots cannot be swapped")
    a.track_id, b.track_id = b.track_id, a.track_id
    a.target_energy, b.target_energy = b.target_energy, a.target_energy
    db.flush()
    return {"slot_a_id": a.id, "slot_b_id": b.id}, {a.position, b.position}


def _tool_remove_slot(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    slot = _slot_or_error(db, set_obj.id, int(payload["slot_id"]))
    if slot.locked:
        raise AgentToolError("Locked slots cannot be removed")
    position = slot.position
    slots = _ordered_slots(db, set_obj.id)
    if any(s.locked and s.position > position for s in slots):
        raise AgentToolError("Remove would move a locked slot")
    db.delete(slot)
    for row in slots:
        if row.id != slot.id and row.position > position:
            row.position -= 1
    db.flush()
    return {"removed_slot_id": slot.id}, {position}


def _tool_insert_from_pool(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    track = _pool_track_or_error(db, set_obj.id, int(payload["pool_track_id"]))
    position = int(payload["position"])
    return _insert_track_at(db, set_obj, track, position)


def _tool_search_and_insert(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    query = str(payload["query"]).strip().lower()
    if not query:
        raise AgentToolError("query is required")
    track = (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_obj.id)
        .order_by(SetPoolTrack.id.asc())
        .all()
    )
    match = next((t for t in track if query in f"{t.title} {t.artist}".lower()), None)
    if match is None:
        raise AgentToolError("No pool track matched query")
    return _insert_track_at(db, set_obj, match, int(payload["position"]))


def _tool_add_slow_window(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    label = str(payload.get("label") or "Slow set")[:50]
    t0_sec = int(payload["t0_sec"])
    t1_sec = int(payload["t1_sec"])
    if t1_sec <= t0_sec:
        raise AgentToolError("t1_sec must be greater than t0_sec")
    windows = curve.get_vibe_windows(db, set_obj.id)
    windows.append({"t0_sec": t0_sec, "t1_sec": t1_sec, "label": label})
    curve.replace_vibe_windows(db, set_obj, windows, commit=False)
    return {"label": label, "t0_sec": t0_sec, "t1_sec": t1_sec}, set()


def _tool_set_peak_at(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    position = int(payload["position"])
    energy = float(payload.get("energy", 10.0))
    slot = _slot_at_position_or_error(db, set_obj.id, position)
    slot.target_energy = round(max(0.0, min(10.0, energy)), 1)
    db.flush()
    return {"slot_id": slot.id, "target_energy": slot.target_energy}, {slot.position}


def _tool_bump_energy(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    amount = float(payload["amount"])
    slot_id = payload.get("slot_id")
    slots = (
        [_slot_or_error(db, set_obj.id, int(slot_id))]
        if slot_id is not None
        else _ordered_slots(db, set_obj.id)
    )
    for slot in slots:
        base = slot.target_energy if slot.target_energy is not None else 5.0
        slot.target_energy = round(max(0.0, min(10.0, base + amount)), 1)
    db.flush()
    return {"updated": len(slots)}, {s.position for s in slots}


def _tool_analyze_transition(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    position = int(payload["position"])
    slots = _ordered_slots(db, set_obj.id)
    if position <= 0 or position >= len(slots):
        raise AgentToolError("position must identify a transition destination")
    tracks = {
        _pass1_track_meta(t).slot_track_id: _pass1_track_meta(t)
        for t in _pool_tracks(db, set_obj.id)
    }
    prev = tracks.get(slots[position - 1].track_id or "")
    curr = tracks.get(slots[position].track_id or "")
    if curr is None:
        raise AgentToolError("slot has no pool metadata")
    score, warnings = transition_score(prev, curr, set_obj.key_strictness)
    return {"position": position, "score": score, "warnings": warnings}, set()


def _tool_summarize_set(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Read-only snapshot of the whole set: duration, BPM arc, key journey, energy.

    Returns ``(summary, set())`` — no positions are affected because nothing is
    mutated. Mirrors ``_tool_analyze_transition`` (read-only), not ``_tool``.
    """
    del payload  # no input args
    slots = _ordered_slots(db, set_obj.id)
    # One view per pool track: meta carries BPM + normalized key, the raw row
    # carries duration_sec (which TrackMeta does not expose).
    by_track_id = {
        _pass1_track_meta(t).slot_track_id: (_pass1_track_meta(t), t)
        for t in _pool_tracks(db, set_obj.id)
    }

    total_duration_sec = 0
    bpms: list[float] = []
    key_journey: list[str] = []
    energy_values: list[float | None] = []
    for slot in slots:
        meta, track = by_track_id.get(slot.track_id or "", (None, None))
        if track is not None and track.duration_sec:
            total_duration_sec += int(track.duration_sec)
        if meta is not None and meta.bpm is not None:
            bpms.append(float(meta.bpm))
        camelot = parse_key(meta.key) if meta is not None else None
        if camelot is not None:
            key_journey.append(str(camelot))
        energy_values.append(slot.target_energy)

    target_duration_sec = set_obj.target_duration_sec
    return {
        "slot_count": len(slots),
        "total_duration_sec": total_duration_sec,
        "target_duration_sec": target_duration_sec,
        "duration_delta_sec": (
            total_duration_sec - target_duration_sec if target_duration_sec is not None else None
        ),
        "bpm_arc": _bpm_arc(bpms),
        "key_journey": key_journey,
        "energy_profile": _energy_profile(energy_values),
    }, set()


def _bpm_arc(bpms: list[float]) -> dict[str, float] | None:
    """Min/max/first/last/mean over slots that have a BPM; ``None`` if none do."""
    if not bpms:
        return None
    return {
        "min": min(bpms),
        "max": max(bpms),
        "first": bpms[0],
        "last": bpms[-1],
        "mean": round(sum(bpms) / len(bpms), 1),
    }


def _energy_profile(values: list[float | None]) -> dict[str, Any]:
    """Ordered ``target_energy`` per slot plus the slot position of the peak."""
    known = [(pos, val) for pos, val in enumerate(values) if val is not None]
    peak_position = max(known, key=lambda pair: pair[1])[0] if known else None
    return {"values": values, "peak_position": peak_position}


def _tool_static_critique(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    del payload
    slots = _ordered_slots(db, set_obj.id)
    scores = [s.transition_score for s in slots[1:] if s.transition_score is not None]
    avg = round(sum(scores) / len(scores), 1) if scores else None
    return {"average_transition_score": avg, "slot_count": len(slots)}, set()


def _insert_track_at(
    db: Session, set_obj: Set, track: SetPoolTrack, position: int
) -> tuple[dict[str, Any], set[int]]:
    slots = _ordered_slots(db, set_obj.id)
    position = max(0, min(len(slots), position))
    if any(s.locked and s.position >= position for s in slots):
        raise AgentToolError("Insert would move a locked slot")
    for slot in slots:
        if slot.position >= position:
            slot.position += 1
    slot_track_id = track.track_id or f"pool:{track.id}"
    db.add(SetSlot(set_id=set_obj.id, position=position, track_id=slot_track_id))
    db.flush()
    return {"pool_track_id": track.id, "position": position}, set(range(position, len(slots) + 1))


def _slot_or_error(db: Session, set_id: int, slot_id: int) -> SetSlot:
    slot = db.query(SetSlot).filter(SetSlot.set_id == set_id, SetSlot.id == slot_id).one_or_none()
    if slot is None:
        raise AgentToolError("Slot not found")
    return slot


def _slot_at_position_or_error(db: Session, set_id: int, position: int) -> SetSlot:
    slot = (
        db.query(SetSlot)
        .filter(SetSlot.set_id == set_id, SetSlot.position == position)
        .one_or_none()
    )
    if slot is None:
        raise AgentToolError("Slot not found")
    return slot


def _pool_track_or_error(db: Session, set_id: int, pool_track_id: int) -> SetPoolTrack:
    track = (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_id, SetPoolTrack.id == pool_track_id)
        .one_or_none()
    )
    if track is None:
        raise AgentToolError("Pool track not found")
    return track


def _ordered_slots(db: Session, set_id: int) -> list[SetSlot]:
    return db.query(SetSlot).filter(SetSlot.set_id == set_id).order_by(SetSlot.position.asc()).all()


def _pool_tracks(db: Session, set_id: int) -> list[SetPoolTrack]:
    return (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_id)
        .order_by(SetPoolTrack.id.asc())
        .all()
    )


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


def _critique_tool() -> ToolSpec:
    return ToolSpec(
        name="critique_set",
        description="Return a structured critique for the current set.",
        input_schema={
            "type": "object",
            "properties": {
                "overall_grade": {"type": "string"},
                "summary": {"type": "string"},
                "flags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "energy_dip",
                                    "vibe_clash",
                                    "era_jump",
                                    "sing_along_missing",
                                    "banger_buried",
                                    "transition_brilliant",
                                ],
                            },
                            "slot_position": {"type": "integer"},
                            "message": {"type": "string"},
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["overall_grade", "flags"],
        },
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


def _position_label(position: int) -> str:
    return f"slot {position + 1}"


def _tool_display_summary(
    name: str,
    payload: dict[str, Any],
    result: dict[str, Any],
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
) -> str:
    if name == "swap_slots":
        a = before.get(int(payload["slot_a_id"]))
        b = before.get(int(payload["slot_b_id"]))
        if a and b:
            return (
                f"Swapped {_position_label(a['position'])} {a['label']} with "
                f"{_position_label(b['position'])} {b['label']}."
            )
    if name == "reorder_slot":
        slot = before.get(int(payload["slot_id"]))
        if slot:
            return (
                f"Moved {slot['label']} from {_position_label(slot['position'])} to "
                f"{_position_label(int(result['position']))}."
            )
    if name == "remove_slot":
        removed = before.get(int(payload["slot_id"]))
        if removed:
            return f"Removed {removed['label']} from {_position_label(removed['position'])}."
    if name in {"insert_from_pool", "search_and_insert"}:
        position = int(result["position"])
        inserted = next((s for s in after.values() if s["position"] == position), None)
        label = inserted["label"] if inserted else "a pool track"
        return f"Added {label} at {_position_label(position)}."
    if name == "bump_energy":
        updated = int(result.get("updated") or 0)
        amount = float(payload["amount"])
        direction = "Raised" if amount >= 0 else "Lowered"
        return (
            f"{direction} target energy by {abs(amount):g} across {updated} "
            f"slot{'s' if updated != 1 else ''}."
        )
    if name == "set_peak_at":
        position = int(payload["position"])
        slot = next((s for s in after.values() if s["position"] == position), None)
        label = f" {slot['label']}" if slot else ""
        return (
            f"Set {_position_label(position)}{label} as the energy peak at "
            f"{float(result['target_energy']):g}."
        )
    if name == "add_slow_window":
        label = str(result.get("label") or "Slow window")
        return (
            f"Added slow window {label} from {int(result['t0_sec'])}s to {int(result['t1_sec'])}s."
        )
    if name == "analyze_transition":
        base = (
            f"Analyzed transition into {_position_label(int(result['position']))}: "
            f"{round(float(result['score']))}."
        )
        warnings = result.get("warnings") or []
        if warnings:
            readable = ", ".join(str(warning).replace("_", " ") for warning in warnings)
            return f"{base} Warnings: {readable}."
        return base
    if name == "summarize_set":
        return _summarize_set_summary(result)
    if name == "critique_set":
        grade = result.get("overall_grade")
        if grade:
            summary = str(result.get("summary") or "").strip()
            head = f"Critique grade {grade}."
            return f"{head} {summary}" if summary else head
        return "Recomputed critique context."
    return name.replace("_", " ").capitalize() + "."


def _summarize_set_summary(result: dict[str, Any]) -> str:
    count = int(result.get("slot_count") or 0)
    total = int(result.get("total_duration_sec") or 0)
    parts = [f"Set has {count} slot{'s' if count != 1 else ''}, {total // 60} min total"]
    delta = result.get("duration_delta_sec")
    if delta is not None and delta != 0:
        over_under = "over" if delta > 0 else "under"
        parts.append(f"{abs(int(delta)) // 60} min {over_under} target")
    arc = result.get("bpm_arc")
    if arc:
        parts.append(f"BPM {arc['min']:g}-{arc['max']:g}")
    return "; ".join(parts) + "."


def _agent_tools() -> list[ToolSpec]:
    return [
        _tool("reorder_slot", {"slot_id": "integer", "position": "integer"}),
        _tool("swap_slots", {"slot_a_id": "integer", "slot_b_id": "integer"}),
        _tool("remove_slot", {"slot_id": "integer"}),
        _tool("insert_from_pool", {"pool_track_id": "integer", "position": "integer"}),
        _tool("search_and_insert", {"query": "string", "position": "integer"}),
        _tool("add_slow_window", {"t0_sec": "integer", "t1_sec": "integer", "label": "string"}),
        _tool("set_peak_at", {"position": "integer", "energy": "number"}),
        _tool("bump_energy", {"amount": "number", "slot_id": "integer"}),
        ToolSpec(
            name="analyze_transition",
            description="Analyze one transition by destination slot position.",
            input_schema={
                "type": "object",
                "properties": {"position": {"type": "integer"}},
                "required": ["position"],
            },
        ),
        ToolSpec(
            name="summarize_set",
            description=(
                "Read-only snapshot of the whole set: total vs target duration, "
                "BPM arc, Camelot key journey, and energy profile."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
        ),
        _critique_tool(),
    ]


def _tool(name: str, fields: dict[str, str]) -> ToolSpec:
    properties = {key: {"type": value} for key, value in fields.items()}
    properties["rationale"] = {"type": "string"}
    return ToolSpec(
        name=name,
        description=f"Mutate the WrzDJSet timeline with {name}.",
        input_schema={
            "type": "object",
            "properties": properties,
            "required": [*fields.keys(), "rationale"],
        },
    )
