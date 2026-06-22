"""Destructive structural WrzDJSet agent tools (#491, #442 Family 3).

``autobuild`` regenerates the whole order from the pool + curve; both tools are
in ``MUTATION_TOOLS`` and dispatched only through ``apply_tool_call``. They are
undoable via the frontend global-undo stack (#493/#494), which snapshots the
whole document before every mutating agent turn.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.set import Set
from app.services.setbuilder.agent_common import AgentToolError, _ordered_slots, _pool_tracks
from app.services.setbuilder.agent_tools_mutations import _insert_track_at
from app.services.setbuilder.pass1_deterministic import AVG_TRACK_LENGTH_SEC, build_set
from app.services.setbuilder.pass1_deterministic import _track_meta as _pass1_track_meta

logger = logging.getLogger(__name__)

# Per-turn safety cap: one fill_to_duration call can never append more than this
# many slots, independent of pool size (the issue's bounded-insert requirement).
MAX_FILL_INSERTS = 100


def _tool_autobuild(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Regenerate the entire ordering from the pool + curve (wholesale).

    Thin owner-scoped wrapper over ``pass1_deterministic.build_set``, which
    already honors locked slots and saved pairings. Runs with ``commit=False``
    so the agent turn commits/rolls back as one unit.
    """
    result = build_set(db, set_obj, commit=False)
    affected = {slot.position for slot in result.slots}
    logger.info(
        "setbuilder autobuild: set %s rebuilt to %s slots (%s refinement iterations)",
        set_obj.id,
        result.slot_count,
        result.iterations,
    )
    return {"slot_count": result.slot_count, "iterations": result.iterations}, affected


def _duration_for(track) -> int:
    """A pool track's duration in seconds, falling back to the pass-1 average."""
    if track is not None and track.duration_sec and track.duration_sec > 0:
        return track.duration_sec
    return AVG_TRACK_LENGTH_SEC


def _tool_fill_to_duration(
    db: Session, set_obj: Set, payload: dict[str, Any]
) -> tuple[dict[str, Any], set[int]]:
    """Append unused pool tracks (in pool order) until the set reaches its
    ``target_duration_sec``, never moving locked slots and never appending more
    than ``MAX_FILL_INSERTS`` in one turn.
    """
    target = set_obj.target_duration_sec
    # Explicit None check: a target of 0 is a valid (if unusual) assigned value —
    # the loop below treats it as "already met" and appends nothing, rather than
    # erroring as if no target were set.
    if target is None:
        raise AgentToolError("Set a target duration first (target_duration_sec).")

    pool = _pool_tracks(db, set_obj.id)
    by_slot_track_id = {_pass1_track_meta(t).slot_track_id: t for t in pool}
    slots = _ordered_slots(db, set_obj.id)
    used = {slot.track_id for slot in slots if slot.track_id}
    total = sum(_duration_for(by_slot_track_id.get(slot.track_id)) for slot in slots)
    candidates = [t for t in pool if _pass1_track_meta(t).slot_track_id not in used]

    base_count = len(slots)
    affected: set[int] = set()
    inserted = 0
    capped = False
    for track in candidates:
        if total >= target:
            break
        if inserted >= MAX_FILL_INSERTS:
            capped = True
            break
        _, positions = _insert_track_at(db, set_obj, track, base_count + inserted)
        affected |= positions
        total += _duration_for(track)
        inserted += 1

    pool_exhausted = total < target and not capped
    logger.info(
        "setbuilder fill_to_duration: set %s added %s tracks (target=%ss, est_total=%ss, "
        "capped=%s, pool_exhausted=%s)",
        set_obj.id,
        inserted,
        target,
        total,
        capped,
        pool_exhausted,
    )
    return {
        "inserted_count": inserted,
        "estimated_total_sec": total,
        "target_duration_sec": target,
        "capped": capped,
        "pool_exhausted": pool_exhausted,
    }, affected
