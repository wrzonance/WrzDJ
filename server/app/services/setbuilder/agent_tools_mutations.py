"""Mutating WrzDJSet agent tools (#442): reorder/swap/remove/replace/insert,
energy + curve edits, set targets, and slot locking.

Every name here is in ``MUTATION_TOOLS`` and is dispatched only through
``apply_tool_call``'s closed allowlist. Owner-scoping and the rationale
requirement are enforced by the caller; handlers enforce locked-slot safety.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolTrack
from app.services.setbuilder import curve, pairings
from app.services.setbuilder.agent_common import (
    AgentToolError,
    _ordered_slots,
    _pool_track_or_error,
    _slot_at_position_or_error,
    _slot_or_error,
)
from app.services.setbuilder.pass1_deterministic import _track_meta as _pass1_track_meta

# Sentinel for set_target: distinguishes an omitted field (leave unchanged) from
# an explicit null (clear a nullable target column).
_UNSET = object()


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


def _tool_move_range(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Relocate the contiguous slot block ``[start_position, end_position]`` so it
    begins at ``to_position`` (clamped to a valid insertion index).

    The span analogue of ``_tool_reorder_slot``: a locked slot may never change
    position (neither dragged inside the block nor displaced by the shift), and
    the handler returns the touched position window for the orchestrator to
    rescore — it does not rescore itself.
    """
    slots = _ordered_slots(db, set_obj.id)
    count = len(slots)
    start = int(payload["start_position"])
    end = int(payload["end_position"])
    if not 0 <= start <= end < count:
        raise AgentToolError("start_position and end_position must be a valid slot range")
    block = slots[start : end + 1]
    if any(slot.locked for slot in block):
        raise AgentToolError("Cannot move a locked slot")
    remaining = slots[:start] + slots[end + 1 :]
    to_position = max(0, min(len(remaining), int(payload["to_position"])))
    new_order = remaining[:to_position] + block + remaining[to_position:]
    if any(slot.locked and slot.position != idx for idx, slot in enumerate(new_order)):
        raise AgentToolError("Move would displace a locked slot")
    for idx, slot in enumerate(new_order):
        slot.position = idx
    db.flush()
    block_len = len(block)
    affected = set(range(min(start, to_position), max(end, to_position + block_len - 1) + 1))
    return {
        "start_position": start,
        "end_position": end,
        "to_position": to_position,
        "moved_count": block_len,
    }, affected


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


def _tool_replace_slot(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Atomic track swap: keep the slot's position, point it at a new pool track.

    A single op that replaces remove+insert, so the timeline never passes through
    a transient invalid state and no positions shift. Mirrors ``_tool_remove_slot``
    for the locked check and the insert tools for the namespaced id derivation.
    """
    slot = _slot_or_error(db, set_obj.id, int(payload["slot_id"]))
    if slot.locked:
        raise AgentToolError("Locked slots cannot be replaced")
    track = _pool_track_or_error(db, set_obj.id, int(payload["pool_track_id"]))
    slot.track_id = _pass1_track_meta(track).slot_track_id
    db.flush()
    return {"slot_id": slot.id, "pool_track_id": track.id}, {slot.position}


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


def _tool_set_curve_point(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Upsert a standalone (non-window) curve point at ``position_sec``.

    Curve points are time-offset markers, not slot positions, so no slot
    positions are affected — returns ``set()`` like ``add_slow_window``.
    """
    position_sec = int(payload["position_sec"])
    energy = int(payload["energy"])
    if not 0 <= energy <= 10:
        raise AgentToolError("energy must be between 0 and 10")
    label = payload.get("label")
    label = str(label)[:50] if label is not None else None
    point = curve.upsert_curve_point(db, set_obj, position_sec, energy, label, commit=False)
    return {
        "point_id": point.id,
        "position_sec": point.position_sec,
        "energy": point.energy,
        "label": point.label,
    }, set()


def _tool_remove_curve_point(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Remove the standalone (non-window) curve point at ``position_sec``.

    Keyed by ``position_sec`` (the agent works from the time-offset curve, not
    DB row ids). Raises ``AgentToolError`` if no non-window point is there, so
    the agent gets a clear signal instead of a silent no-op.
    """
    position_sec = int(payload["position_sec"])
    removed = curve.remove_curve_point(db, set_obj, position_sec, commit=False)
    if not removed:
        raise AgentToolError("No curve point at that position_sec")
    return {"removed_position_sec": position_sec}, set()


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


def _tool_add_pairing(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Pin a transition as a DJ pairing (#442): the from->into pair gets a +20
    pass-1 ordering boost. Owner-scoped via the pool tracks; writes only the
    set's pairings, never the requests table.

    Affects no slot positions or stored scores (the boost steers future pass-1
    candidate ordering, not the current adjacency), so the affected set is empty.
    The service runs with ``commit=False`` so the agent turn commits/rolls back
    as one unit.
    """
    from_track_id, from_track = _pairing_endpoint(db, set_obj, payload, "from_pool_track_id")
    into_track_id, into_track = _pairing_endpoint(db, set_obj, payload, "into_pool_track_id")
    if from_track_id == into_track_id:
        raise AgentToolError("A pairing needs two different tracks")
    note = payload.get("note")
    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        raise AgentToolError("tags must be a list of strings")
    try:
        pairing, created = pairings.upsert_pairing(
            db,
            set_obj,
            from_track_id=from_track_id,
            into_track_id=into_track_id,
            cue_in_sec=None,
            note=str(note)[:500] if note is not None else None,
            tags=[str(tag) for tag in tags],
            commit=False,
        )
    except ValueError as exc:
        raise AgentToolError(str(exc)) from exc
    return {
        "pairing_id": pairing.id,
        "from_track_id": from_track_id,
        "into_track_id": into_track_id,
        "from_label": from_track.title,
        "into_label": into_track.title,
        "created": created,
    }, set()


def _tool_remove_pairing(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Unpin a saved transition pairing (#442), keyed by its two pool tracks.

    Symmetric with ``_tool_add_pairing``; raises when no pairing exists so the
    agent gets a clear signal instead of a silent no-op. Commit deferred to the
    turn.
    """
    from_track_id, from_track = _pairing_endpoint(db, set_obj, payload, "from_pool_track_id")
    into_track_id, into_track = _pairing_endpoint(db, set_obj, payload, "into_pool_track_id")
    pairing = pairings.find_pairing(db, set_obj.id, from_track_id, into_track_id)
    if pairing is None:
        raise AgentToolError("No saved pairing for that transition")
    pairings.delete_pairing(db, pairing, commit=False)
    return {
        "removed": True,
        "from_track_id": from_track_id,
        "into_track_id": into_track_id,
        "from_label": from_track.title,
        "into_label": into_track.title,
    }, set()


def _pairing_endpoint(
    db: Session, set_obj: Set, payload: dict[str, Any], field_name: str
) -> tuple[str, SetPoolTrack]:
    """Resolve a pool-track id from ``payload`` to its (namespaced track_id, row).

    The pairing key must be the same namespaced id slots use, so derive it via
    the Pass-1 track meta — keeping pairings, slots, and the boost lookup aligned.
    """
    track = _pool_track_or_error(db, set_obj.id, int(payload[field_name]))
    return _pass1_track_meta(track).slot_track_id, track
