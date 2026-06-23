"""Shared errors, the mutation allowlist, and DB lookup helpers for the
WrzDJSet agent toolkit (#442).

Extracted from pass2_agent.py so the per-concern tool modules and the
orchestration facade share one dependency-free foundation without import cycles.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.set import SetSlot
from app.models.set_pool import SetPoolTrack

MUTATION_TOOLS = {
    "reorder_slot",
    "move_range",
    "swap_slots",
    "remove_slot",
    "replace_slot",
    "insert_from_pool",
    "search_and_insert",
    "add_slow_window",
    "set_peak_at",
    "bump_energy",
    "set_curve_point",
    "remove_curve_point",
    "apply_curve_template",
    "autobuild",
    "fill_to_duration",
    "set_target",
    "lock_slot",
    "unlock_slot",
    "add_pairing",
    "remove_pairing",
    "import_from_event",
    "import_from_tidal",
    "import_from_beatport",
    "import_from_url",
}


class AgentToolError(ValueError):
    """The model requested an invalid or unsafe setbuilder tool operation."""


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
