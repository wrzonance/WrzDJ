"""Shared ownership and response helpers for set-builder routes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.set import Set
from app.models.user import User
from app.schemas.setbuilder import TransitionScoreOut
from app.services.setbuilder.set_service import get_owned_set

if TYPE_CHECKING:
    from app.services.setbuilder.pass1_deterministic import TransitionScore


def get_owned_set_or_404(db: Session, set_id: int, user: User) -> Set:
    """Return a set owned by the caller, hiding missing and foreign-owned IDs."""
    set_obj = get_owned_set(db, set_id, user.id)
    if set_obj is None:
        raise HTTPException(status_code=404, detail="Set not found")
    return set_obj


def transition_scores_out(scores: Sequence[TransitionScore]) -> list[TransitionScoreOut]:
    """Map service transition scores to the API response schema."""
    return [
        TransitionScoreOut(
            slot_id=score.slot_id,
            position=score.position,
            score=score.score,
            warnings=score.warnings,
        )
        for score in scores
    ]
