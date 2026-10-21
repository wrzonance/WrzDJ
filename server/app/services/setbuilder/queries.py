"""Shared ordered queries for a set's slots and pool tracks."""

from sqlalchemy.orm import Session

from app.models.set import SetSlot
from app.models.set_pool import SetPoolTrack


def ordered_slots(db: Session, set_id: int) -> list[SetSlot]:
    """Return a set's slots in timeline order."""
    return db.query(SetSlot).filter(SetSlot.set_id == set_id).order_by(SetSlot.position.asc()).all()


def pool_tracks(db: Session, set_id: int) -> list[SetPoolTrack]:
    """Return a set's pool tracks in stable insertion order."""
    return (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_id)
        .order_by(SetPoolTrack.id.asc())
        .all()
    )
