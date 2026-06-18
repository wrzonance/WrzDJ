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
    TrackMeta,
    TransitionScore,
    recompute_transition_scores,
    transition_score,
)
from app.services.setbuilder.pass1_deterministic import _track_meta as _pass1_track_meta
from app.services.setbuilder.vibe_resolver import TrackVibeState, build_pool_vibe_state

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
    "apply_curve_template",
    "set_target",
    "lock_slot",
    "unlock_slot",
}
ALLOWED_FLAG_TYPES = {
    "energy_dip",
    "vibe_clash",
    "era_jump",
    "sing_along_missing",
    "banger_buried",
    "transition_brilliant",
}

# The 24 Camelot-wheel slots: numbers 1-12 on each of the A (minor) and B
# (major) rings. Used by analyze_pool_gaps to report which slots the pool
# leaves uncovered.
ALL_CAMELOT_KEYS: tuple[str, ...] = tuple(
    f"{number}{letter}" for number in range(1, 13) for letter in ("A", "B")
)
# analyze_pool_gaps bins pool BPMs into fixed-width bands; a band holding
# fewer than SPARSE_BAND_THRESHOLD tracks is flagged as a coverage hole.
BPM_BAND_WIDTH = 10
SPARSE_BAND_THRESHOLD = 2


class AgentToolError(ValueError):
    """The model requested an invalid or unsafe setbuilder tool operation."""


# Sentinel for set_target: distinguishes an omitted field (leave unchanged) from
# an explicit null (clear a nullable target column).
_UNSET = object()


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
        "apply_curve_template": _tool_apply_curve_template,
        "set_target": _tool_set_target,
        "lock_slot": _tool_lock_slot,
        "unlock_slot": _tool_unlock_slot,
        "analyze_transition": _tool_analyze_transition,
        "explain_transition": _tool_explain_transition,
        "get_track_vibes": _tool_get_track_vibes,
        "summarize_set": _tool_summarize_set,
        "analyze_pool_gaps": _tool_analyze_pool_gaps,
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


def _tool_apply_curve_template(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Re-target every (unlocked) slot from a built-in or owned template shape.

    Reuses the curve service the REST endpoint uses. ``locked`` slots are
    protected: ``apply_points_to_slots`` re-targets every slot uniformly, so we
    snapshot the locked slots' ``target_energy`` first and restore it after,
    leaving their DJ-chosen energy untouched. Their positions are excluded from
    the affected set and from the returned targets.
    """
    points = _curve_template_points(db, set_obj, payload)
    # apply_points_to_slots re-targets EVERY slot, so snapshot locked targets
    # first to restore them afterward; its return value is ignored because we
    # rebuild the locked-aware targets from the slots below.
    locked_before = {
        slot.id: slot.target_energy for slot in _ordered_slots(db, set_obj.id) if slot.locked
    }
    try:
        curve.apply_points_to_slots(db, set_obj, points, None)
    except ValueError as exc:
        raise AgentToolError(str(exc)) from exc

    targets: list[dict[str, Any]] = []
    affected: set[int] = set()
    for slot in _ordered_slots(db, set_obj.id):
        if slot.id in locked_before:
            slot.target_energy = locked_before[slot.id]
            continue
        targets.append({"slot_id": slot.id, "target_energy": slot.target_energy})
        affected.add(slot.position)
    if locked_before:
        db.flush()

    return {"targets": targets, "windows": curve.windows_from_points(points)}, affected


def _curve_template_points(db: Session, set_obj: Set, payload: dict[str, Any]) -> list[dict]:
    """Resolve the template (built-in name XOR owned id) to its point list."""
    builtin = payload.get("builtin")
    template_id = payload.get("template_id")
    if builtin is not None:
        points = curve.BUILTIN_TEMPLATES.get(str(builtin))
        if points is None:
            raise AgentToolError("Template not found")
        return points
    if template_id is not None:
        tpl = curve.get_owned_template(db, int(template_id), set_obj.owner_id)
        if tpl is None:
            raise AgentToolError("Template not found")
        return curve.template_points(tpl)
    raise AgentToolError("apply_curve_template requires builtin or template_id")


def _tool_set_target(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Set whichever of the Set's targets are present in ``payload`` (#465).

    Each field is OPTIONAL: an omitted key leaves the column untouched, while an
    explicit ``null`` clears a nullable column. Writes only ``set_obj``'s target
    columns — never the ``requests`` table. Targets shape future deterministic
    passes but move no slots, so the affected-positions set is always empty.
    """
    updates = _resolve_target_updates(payload)
    _validate_bpm_window(set_obj, updates)
    for column, value in updates.items():
        setattr(set_obj, column, value)
    db.flush()
    return updates, set()


def _resolve_target_updates(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull, coerce, and range-check the target fields actually present in payload."""
    updates: dict[str, Any] = {}
    _set_nonneg_int(updates, payload, "target_duration_sec", nullable=True)
    _set_optional_int(updates, payload, "bpm_floor")
    _set_optional_int(updates, payload, "bpm_ceiling")
    _set_key_strictness(updates, payload)
    _set_nonneg_int(updates, payload, "avg_transition_overlap_sec", nullable=False)
    return updates


def _set_nonneg_int(
    updates: dict[str, Any], payload: dict[str, Any], field_name: str, *, nullable: bool
) -> None:
    value = payload.get(field_name, _UNSET)
    if value is _UNSET:
        return
    if value is None:
        if not nullable:
            raise AgentToolError(f"{field_name} cannot be null")
        updates[field_name] = None
        return
    coerced = int(value)
    if coerced < 0:
        raise AgentToolError(f"{field_name} must be non-negative")
    updates[field_name] = coerced


def _set_optional_int(updates: dict[str, Any], payload: dict[str, Any], field_name: str) -> None:
    value = payload.get(field_name, _UNSET)
    if value is _UNSET:
        return
    updates[field_name] = None if value is None else int(value)


def _set_key_strictness(updates: dict[str, Any], payload: dict[str, Any]) -> None:
    value = payload.get("key_strictness", _UNSET)
    if value is _UNSET:
        return
    if value is None:
        raise AgentToolError("key_strictness cannot be null")
    coerced = float(value)
    if not 0.0 <= coerced <= 1.0:
        raise AgentToolError("key_strictness must be between 0.0 and 1.0")
    updates["key_strictness"] = coerced


def _validate_bpm_window(set_obj: Set, updates: dict[str, Any]) -> None:
    """Reject an inverted BPM window, considering both new and already-stored bounds."""
    floor = updates["bpm_floor"] if "bpm_floor" in updates else set_obj.bpm_floor
    ceiling = updates["bpm_ceiling"] if "bpm_ceiling" in updates else set_obj.bpm_ceiling
    if floor is not None and ceiling is not None and floor > ceiling:
        raise AgentToolError("bpm_floor must be <= bpm_ceiling")


def _tool_lock_slot(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    return _set_slot_locked(db, set_obj, payload, locked=True)


def _tool_unlock_slot(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    return _set_slot_locked(db, set_obj, payload, locked=False)


def _set_slot_locked(
    db: Session, set_obj: Set, payload: dict[str, Any], *, locked: bool
) -> tuple[dict[str, Any], set[int]]:
    """Pin/unpin a slot: write only its ``locked`` column. Idempotent."""
    try:
        slot_id = int(payload["slot_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentToolError("slot_id must be an integer") from exc
    slot = _slot_or_error(db, set_obj.id, slot_id)
    slot.locked = locked
    db.flush()
    return {"slot_id": slot.id, "locked": locked, "position": slot.position}, {slot.position}


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


def _tool_explain_transition(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Read-only: turn a transition's terse warning codes into grounded sentences."""
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
    explanations = [
        {"code": code, "detail": _explain_warning(code, prev, curr)} for code in warnings
    ]
    return {
        "position": position,
        "score": score,
        "explanations": explanations,
        "prev": _track_summary(prev),
        "curr": _track_summary(curr),
    }, set()


def _track_summary(meta: TrackMeta | None) -> dict[str, Any] | None:
    """Compact prev/curr summary of the fields that drive transition scoring."""
    if meta is None:
        return None
    return {
        "title": meta.title,
        "artist": meta.artist,
        "bpm": meta.bpm,
        "key": meta.key,
        "energy": meta.energy,
    }


def _explain_warning(code: str, prev: TrackMeta | None, curr: TrackMeta) -> str:
    """Build one human-readable sentence for a warning, grounded in real fields."""
    if code == "bpm_jump":
        prev_bpm = _fmt_number(prev.bpm) if prev else "unknown"
        return (
            f"Big tempo gap: {prev_bpm} BPM into {_fmt_number(curr.bpm)} BPM — "
            "too far to ride the same groove."
        )
    if code == "key_clash":
        prev_key = prev.key if (prev and prev.key) else "unknown"
        return (
            f"Keys clash: {prev_key} into {curr.key or 'unknown'} are not "
            "harmonically adjacent on the Camelot wheel."
        )
    if code == "mood_shift":
        # Forward-looking: transition_score may emit mood_shift, but the current
        # pool→TrackMeta path never populates mood (SetPoolTrack has no mood column),
        # so this branch is defensive and only exercised directly by unit tests today.
        prev_mood = prev.mood if (prev and prev.mood) else "unknown"
        return (
            f"Mood swings from {prev_mood} to {curr.mood or 'unknown'} — "
            "the emotional energy lurches."
        )
    if code == "repeat_artist":
        artist = curr.artist or (prev.artist if prev else None) or "the same artist"
        return f"Back-to-back {artist}: repeating an artist can stall the set's variety."
    return code.replace("_", " ")


def _fmt_number(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:g}"


def _tool_get_track_vibes(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Read-only: surface a slot track's resolved TrackVibe tags (#457).

    Resolves the slot -> its pool track -> the owner-merged vibe state via
    ``vibe_resolver``. No vibe data yields an explicit empty result, never an
    error. Writes to no table; returns ``set()`` (no affected positions).
    """
    slot = _slot_or_error(db, set_obj.id, int(payload["slot_id"]))
    owner = db.get(User, set_obj.owner_id)
    if owner is None:
        raise AgentToolError("Set owner not found")
    pool_track = _slot_pool_track(db, set_obj.id, slot.track_id)
    state = (
        build_pool_vibe_state(db, owner, set_obj, pool_track.id) if pool_track is not None else None
    )
    return _vibe_state_result(slot, pool_track, state), set()


def _slot_pool_track(db: Session, set_id: int, slot_track_id: str | None) -> SetPoolTrack | None:
    """Map a slot's namespaced track_id back to its pool track row, if any."""
    for track in _pool_tracks(db, set_id):
        if _pass1_track_meta(track).slot_track_id == (slot_track_id or ""):
            return track
    return None


def _vibe_state_result(
    slot: SetSlot, pool_track: SetPoolTrack | None, state: TrackVibeState | None
) -> dict[str, Any]:
    """Shape a TrackVibeState into the agent-facing vibe result payload."""
    resolved = state.resolved if state else None
    has_vibe = resolved is not None and (resolved.energy is not None or resolved.mood is not None)
    return {
        "slot_id": slot.id,
        "position": slot.position,
        "pool_track_id": pool_track.id if pool_track else None,
        "has_vibe": has_vibe,
        "resolved": {
            "energy": resolved.energy if resolved else None,
            "energy_source": resolved.energy_source if resolved else None,
            "mood": resolved.mood if resolved else None,
            "mood_source": resolved.mood_source if resolved else None,
        },
    }


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


def _tool_analyze_pool_gaps(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Read-only coverage report over the set's pool (missing keys + BPM bands)."""
    del payload
    metas = [_pass1_track_meta(t) for t in _pool_tracks(db, set_obj.id)]
    camelot_keys = [str(pos) for pos in (parse_key(m.key) for m in metas) if pos is not None]
    bpms = [float(m.bpm) for m in metas if m.bpm is not None]
    present = set(camelot_keys)
    missing = [key for key in ALL_CAMELOT_KEYS if key not in present]
    bands = _bpm_bands(set_obj, bpms)
    logger.debug(
        "Set %s analyze_pool_gaps: pool=%d keyed=%d bpm=%d missing_keys=%d",
        set_obj.id,
        len(metas),
        len(camelot_keys),
        len(bpms),
        len(missing),
    )
    return {
        "pool_size": len(metas),
        "keyed_track_count": len(camelot_keys),
        "bpm_track_count": len(bpms),
        "missing_camelot_keys": missing,
        "bpm_bands": bands,
        "sparse_bands": [b for b in bands if b["count"] < SPARSE_BAND_THRESHOLD],
    }, set()


def _bpm_bands(set_obj: Set, bpms: list[float]) -> list[dict[str, Any]]:
    """Bucket pool BPMs into fixed-width bands across the set's target window.

    Bands are anchored to ``set_obj.bpm_floor``..``bpm_ceiling`` (the declared
    window) when set, else the observed pool min/max. The range is then widened
    to also cover any track outside that window, so every BPM-tagged pool track
    lands in exactly one band — ``sum(band counts) == bpm_track_count`` always
    holds, and out-of-window tracks surface as their own bands rather than
    silently vanishing. Empty bands are included so the agent sees tempo holes,
    not just where tracks cluster.
    """
    if not bpms:
        return []
    floor = set_obj.bpm_floor if set_obj.bpm_floor is not None else int(min(bpms))
    ceiling = set_obj.bpm_ceiling if set_obj.bpm_ceiling is not None else int(max(bpms))
    low = min(floor, int(min(bpms)))
    high = max(ceiling, int(max(bpms)))
    start = (low // BPM_BAND_WIDTH) * BPM_BAND_WIDTH
    bands: list[dict[str, Any]] = []
    edge = start
    while edge <= high:
        band_end = edge + BPM_BAND_WIDTH
        count = sum(1 for bpm in bpms if edge <= bpm < band_end)
        bands.append({"label": f"{edge}-{band_end}", "min": edge, "max": band_end, "count": count})
        edge = band_end
    return bands


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
    if name in {"lock_slot", "unlock_slot"}:
        slot = before.get(int(result["slot_id"]))
        verb = "Locked" if result.get("locked") else "Unlocked"
        where = _position_label(slot["position"]) if slot else f"slot {result['slot_id']}"
        return f"{verb} {where}."
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
    if name == "apply_curve_template":
        shape = str(payload.get("builtin") or "saved template")
        count = len(result.get("targets") or [])
        return f"Applied curve template {shape} to {count} slot{'s' if count != 1 else ''}."
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
    if name == "explain_transition":
        base = f"Explained transition into {_position_label(int(result['position']))}."
        explanations = result.get("explanations") or []
        if explanations:
            details = " ".join(str(item.get("detail") or "") for item in explanations)
            return f"{base} {details}".strip()
        return f"{base} No transition issues."
    if name == "get_track_vibes":
        where = _position_label(int(result["position"]))
        if not result.get("has_vibe"):
            return f"No vibe tags on record for {where}."
        resolved = result.get("resolved") or {}
        parts = []
        if resolved.get("energy") is not None:
            parts.append(f"energy {resolved['energy']} ({resolved.get('energy_source')})")
        if resolved.get("mood"):
            parts.append(f"mood {resolved['mood']} ({resolved.get('mood_source')})")
        return f"Vibe tags for {where}: {', '.join(parts)}."
    if name == "set_target":
        return _set_target_summary(result)
    if name == "summarize_set":
        return _summarize_set_summary(result)
    if name == "analyze_pool_gaps":
        missing = result.get("missing_camelot_keys") or []
        sparse = result.get("sparse_bands") or []
        return (
            f"Analyzed pool gaps over {int(result.get('pool_size') or 0)} tracks: "
            f"{len(missing)} missing Camelot key{'s' if len(missing) != 1 else ''}, "
            f"{len(sparse)} sparse BPM band{'s' if len(sparse) != 1 else ''}."
        )
    if name == "critique_set":
        grade = result.get("overall_grade")
        if grade:
            summary = str(result.get("summary") or "").strip()
            head = f"Critique grade {grade}."
            return f"{head} {summary}" if summary else head
        return "Recomputed critique context."
    return name.replace("_", " ").capitalize() + "."


def _set_target_summary(result: dict[str, Any]) -> str:
    """One human-readable sentence over only the target fields the call set."""
    parts: list[str] = []
    if "target_duration_sec" in result:
        secs = result["target_duration_sec"]
        if secs is None:
            parts.append("cleared duration target")
        else:
            parts.append(f"duration {int(secs) // 60} min")
    parts.extend(_bpm_window_summary_parts(result))
    if "key_strictness" in result:
        parts.append(f"key strictness {float(result['key_strictness']):g}")
    if "avg_transition_overlap_sec" in result:
        parts.append(f"transition overlap {int(result['avg_transition_overlap_sec'])}s")
    if not parts:
        return "Updated set targets."
    return "Set targets: " + ", ".join(parts) + "."


def _bpm_window_summary_parts(result: dict[str, Any]) -> list[str]:
    """Render the BPM bounds the call set: combined as a window when both are present."""
    floor, ceiling = result.get("bpm_floor"), result.get("bpm_ceiling")
    has_floor, has_ceiling = "bpm_floor" in result, "bpm_ceiling" in result
    if has_floor and has_ceiling and floor is not None and ceiling is not None:
        return [f"BPM {int(floor)}-{int(ceiling)}"]
    parts: list[str] = []
    if has_floor:
        parts.append("cleared BPM floor" if floor is None else f"BPM floor {int(floor)}")
    if has_ceiling:
        parts.append("cleared BPM ceiling" if ceiling is None else f"BPM ceiling {int(ceiling)}")
    return parts


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
        _tool("lock_slot", {"slot_id": "integer"}),
        _tool("unlock_slot", {"slot_id": "integer"}),
        ToolSpec(
            name="set_target",
            description=(
                "Set the set's goals: total duration, BPM window, key strictness, and "
                "average transition overlap. All target fields are optional — set only "
                "those you want to change; omit the rest. The _tool() helper marks every "
                "field required, so this uses a bare ToolSpec to keep the targets optional "
                "while still requiring rationale (enforced via MUTATION_TOOLS)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "target_duration_sec": {"type": ["integer", "null"], "minimum": 0},
                    "bpm_floor": {"type": ["integer", "null"]},
                    "bpm_ceiling": {"type": ["integer", "null"]},
                    "key_strictness": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "avg_transition_overlap_sec": {"type": "integer", "minimum": 0},
                    "rationale": {"type": "string"},
                },
                "required": ["rationale"],
            },
        ),
        ToolSpec(
            name="apply_curve_template",
            description=(
                "Re-target every unlocked slot's energy from an energy-curve "
                "template shape. Provide exactly one of builtin (a preset name) "
                "or template_id (one of the DJ's saved templates)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "builtin": {
                        "type": "string",
                        "enum": sorted(curve.BUILTIN_TEMPLATES.keys()),
                    },
                    "template_id": {"type": "integer"},
                    "rationale": {"type": "string"},
                },
                "required": ["rationale"],
            },
        ),
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
            name="explain_transition",
            description="Explain why a transition is flagged, grounded in the two tracks' fields.",
            input_schema={
                "type": "object",
                "properties": {"position": {"type": "integer"}},
                "required": ["position"],
            },
        ),
        ToolSpec(
            name="get_track_vibes",
            description="Read the resolved vibe tags (energy, mood, source) for one slot's track.",
            input_schema={
                "type": "object",
                "properties": {"slot_id": {"type": "integer"}},
                "required": ["slot_id"],
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
        ToolSpec(
            name="analyze_pool_gaps",
            description=("Report pool coverage holes: missing Camelot keys and sparse BPM bands."),
            input_schema={"type": "object", "properties": {}},
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
