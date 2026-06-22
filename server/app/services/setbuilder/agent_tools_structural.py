"""Destructive structural WrzDJSet agent tools (#491, #442 Family 3).

``autobuild`` regenerates the whole order from the pool + curve; both tools are
in ``MUTATION_TOOLS`` and dispatched only through ``apply_tool_call``. They are
undoable via the frontend global-undo stack (#493/#494), which snapshots the
whole document before every mutating agent turn.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.set import Set
from app.services.setbuilder.pass1_deterministic import build_set


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
    return {"slot_count": result.slot_count, "iterations": result.iterations}, affected
