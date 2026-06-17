"""DJ-driven full-order slot reordering for WrzDJSet (#437).

Reuses Pass-1 transition scoring so a hand-drag reorder scores identically to
the agent's ``reorder_slot`` tool.
"""

from sqlalchemy.orm import Session

from app.models.set import Set
from app.services.setbuilder.pass1_deterministic import (
    TransitionScore,
    recompute_transition_scores,
)


class ReorderError(ValueError):
    """Requested order is not a permutation, or would move a locked slot."""


def apply_slot_order(
    db: Session, set_obj: Set, ordered_ids: list[int], *, commit: bool = True
) -> list[TransitionScore]:
    """Reassign slot positions to match ``ordered_ids`` and rescore transitions.

    * ``ordered_ids`` must be a permutation of the set's current slot ids.
    * Every locked slot must keep its current position (immovable anchor).
    """
    slots = sorted(set_obj.slots, key=lambda s: s.position)
    if sorted(ordered_ids) != sorted(s.id for s in slots):
        raise ReorderError("slot_ids must be a permutation of the set's slots")

    by_id = {s.id: s for s in slots}
    for new_position, slot_id in enumerate(ordered_ids):
        slot = by_id[slot_id]
        if slot.locked and slot.position != new_position:
            raise ReorderError("Reorder would move a locked slot")

    reordered = [by_id[slot_id] for slot_id in ordered_ids]
    for new_position, slot in enumerate(reordered):
        slot.position = new_position
    return recompute_transition_scores(db, set_obj, reordered, commit=commit)
