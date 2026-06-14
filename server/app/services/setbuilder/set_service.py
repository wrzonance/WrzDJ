"""Owner-scoped CRUD for WrzDJSet sets (Phase 0).

All reads/mutations are scoped to the owner. The API layer surfaces a 404
(not 403) for a missing-or-unowned set to avoid leaking existence, matching
the rest of WrzDJ (see deps.get_owned_event_by_id).
"""

from sqlalchemy.orm import Session

from app.models.set import Set


def create_set(db: Session, owner_id: int, name: str, event_id: int | None = None) -> Set:
    """Create a new empty set owned by `owner_id`."""
    new_set = Set(owner_id=owner_id, name=name, event_id=event_id)
    db.add(new_set)
    db.commit()
    db.refresh(new_set)
    return new_set


def list_sets(db: Session, owner_id: int) -> list[Set]:
    """List the owner's sets, newest first."""
    return db.query(Set).filter(Set.owner_id == owner_id).order_by(Set.created_at.desc()).all()


def get_owned_set(db: Session, set_id: int, owner_id: int) -> Set | None:
    """Fetch a set by id, scoped to the owner. None if missing or unowned."""
    return db.query(Set).filter(Set.id == set_id, Set.owner_id == owner_id).one_or_none()


def rename_set(db: Session, set_obj: Set, name: str) -> Set:
    """Rename a set."""
    set_obj.name = name
    db.commit()
    db.refresh(set_obj)
    return set_obj


def update_target_settings(
    db: Session,
    set_obj: Set,
    *,
    target_duration_sec: int | None,
    avg_transition_overlap_sec: int,
) -> Set:
    """Update set-length planning settings."""
    set_obj.target_duration_sec = target_duration_sec
    set_obj.avg_transition_overlap_sec = avg_transition_overlap_sec
    db.commit()
    db.refresh(set_obj)
    return set_obj


def delete_set(db: Session, set_obj: Set) -> None:
    """Delete a set (children cascade via FK ondelete + ORM cascade)."""
    db.delete(set_obj)
    db.commit()
