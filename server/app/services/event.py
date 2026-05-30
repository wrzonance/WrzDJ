import secrets
import string
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request
from app.models.user import User
from app.schemas.event import EventStatus


class EventLookupResult(str, Enum):
    """Result of looking up an event by code."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    ARCHIVED = "archived"


def generate_event_code(length: int = 6) -> str:
    """Generate a random alphanumeric event code."""
    alphabet = string.ascii_uppercase + string.digits
    # Remove confusing characters
    alphabet = alphabet.replace("0", "").replace("O", "").replace("I", "").replace("1", "")
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_unique_event_code(db: Session, length: int = 6) -> str:
    """Generate a code that is unique across BOTH `code` and `join_code` columns.

    Prevents a value from being reused as the other type, which would collapse
    the collection/live split.
    """
    while True:
        candidate = generate_event_code(length)
        exists = (
            db.query(Event.id)
            .filter(or_(Event.code == candidate, Event.join_code == candidate))
            .first()
        )
        if not exists:
            return candidate


def get_event_by_collection_code(db: Session, code: str) -> Event | None:
    """Resolve an event by its collection code (gated routes: /collect/*)."""
    return db.query(Event).filter(Event.code == code.upper()).first()


def get_event_by_join_code(db: Session, join_code: str) -> Event | None:
    """Resolve an event by its live/join code (frictionless routes: /join, /e/.../display)."""
    return db.query(Event).filter(Event.join_code == join_code.upper()).first()


def compute_event_status(event: Event) -> EventStatus:
    """Compute the status of an event based on its state."""
    if event.archived_at is not None:
        return EventStatus.ARCHIVED
    if event.expires_at <= utcnow() or not event.is_active:
        return EventStatus.EXPIRED
    return EventStatus.ACTIVE


def create_event(db: Session, name: str, user: User, expires_hours: int = 6) -> Event:
    """Create a new event with distinct, globally-unique collection and join codes.

    Concurrency safety: in-memory generation is best-effort; the database
    UNIQUE constraints on `code` and `join_code` are the actual guarantee.
    If two concurrent transactions race and pick overlapping values, the
    INSERT raises IntegrityError and we retry with fresh codes.
    """
    from sqlalchemy.exc import IntegrityError

    expires_at = utcnow() + timedelta(hours=expires_hours)
    max_attempts = 8
    for attempt in range(max_attempts):
        code = generate_unique_event_code(db)
        # Ensure the second code is distinct from the first in-memory candidate;
        # generate_unique_event_code only consults persisted rows.
        while True:
            join_code = generate_unique_event_code(db)
            if join_code != code:
                break

        event = Event(
            code=code,
            join_code=join_code,
            name=name,
            created_by_user_id=user.id,
            expires_at=expires_at,
            frictionless_join=user.frictionless_join_default,
        )
        db.add(event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt == max_attempts - 1:
                raise
            continue
        db.refresh(event)
        return event
    # Unreachable: loop either returns or raises on the final iteration.
    raise RuntimeError("create_event: exhausted retries without resolution")


def get_event_by_code_with_status(db: Session, code: str) -> tuple[Event | None, EventLookupResult]:
    """
    Get an event by COLLECTION code and return lookup result status.

    Used by DJ-facing routes, bridge integration, and any internal lookup that
    starts from the canonical event identifier. For guest-facing live routes
    (/join, /e/.../display, /kiosk-link), use get_event_by_join_code_with_status.
    """
    event = db.query(Event).filter(Event.code == code.upper()).first()
    return _event_with_status(event)


def get_event_by_join_code_with_status(
    db: Session, join_code: str
) -> tuple[Event | None, EventLookupResult]:
    """Get an event by LIVE join code (the QR target) and return lookup status."""
    event = db.query(Event).filter(Event.join_code == join_code.upper()).first()
    return _event_with_status(event)


def _event_with_status(event: Event | None) -> tuple[Event | None, EventLookupResult]:
    if not event:
        return None, EventLookupResult.NOT_FOUND
    if event.archived_at is not None:
        return event, EventLookupResult.ARCHIVED
    if event.expires_at <= utcnow() or not event.is_active:
        return event, EventLookupResult.EXPIRED
    return event, EventLookupResult.FOUND


def get_events_for_user(db: Session, user: User) -> list[Event]:
    """Get all events created by a user."""
    return (
        db.query(Event)
        .filter(Event.created_by_user_id == user.id)
        .order_by(Event.created_at.desc())
        .all()
    )


def update_event(
    db: Session,
    event: Event,
    name: str | None = None,
    expires_at: datetime | None = None,
    frictionless_join: bool | None = None,
) -> Event:
    """Update an event's properties."""
    if name is not None:
        event.name = name
    if expires_at is not None:
        event.expires_at = expires_at
    if frictionless_join is not None:
        event.frictionless_join = frictionless_join
    db.commit()
    db.refresh(event)
    return event


def get_event_by_code_for_owner(db: Session, code: str, user: User) -> Event | None:
    """Get an event by code, owned by the user (regardless of expiry)."""
    return (
        db.query(Event)
        .filter(
            Event.code == code.upper(),
            Event.created_by_user_id == user.id,
        )
        .first()
    )


def delete_event(db: Session, event: Event) -> None:
    """Delete an event and all its associated data.

    Deletes in FK-safe order to avoid constraint violations:
    1. Clean up banner files
    2. Bulk-delete child records (requests cascade-delete votes at DB level)
    3. Delete event (DB cascades delete play_history and now_playing)
    """
    from app.models.now_playing import NowPlaying
    from app.models.play_history import PlayHistory
    from app.models.request_vote import RequestVote
    from app.services.banner import delete_banner_files

    event_id = event.id

    # Clean up banner files before deleting
    delete_banner_files(event.banner_filename)

    # Delete child records in FK-safe order
    db.query(NowPlaying).filter(NowPlaying.event_id == event_id).delete(synchronize_session=False)
    db.query(PlayHistory).filter(PlayHistory.event_id == event_id).delete(synchronize_session=False)
    # Delete votes before requests (SQLite doesn't enforce FK cascades)
    request_ids = [r[0] for r in db.query(Request.id).filter(Request.event_id == event_id).all()]
    if request_ids:
        db.query(RequestVote).filter(RequestVote.request_id.in_(request_ids)).delete(
            synchronize_session=False
        )
    db.query(Request).filter(Request.event_id == event_id).delete(synchronize_session=False)

    # Expunge event from session to skip ORM relationship processing,
    # then bulk-delete the event row directly
    db.expunge(event)
    db.query(Event).filter(Event.id == event_id).delete(synchronize_session=False)
    db.commit()


def bulk_delete_events(db: Session, codes: list[str], user: User | None = None) -> int:
    """Delete multiple events by code in one operation.

    Validates all codes before deleting any (atomic). If user is provided,
    all events must be owned by that user. If user is None (admin mode),
    ownership is not checked.

    Raises ValueError if any code is not found or not owned by the user.
    """
    uppercased = [c.upper() for c in codes]
    events = db.query(Event).filter(Event.code.in_(uppercased)).all()

    # Build a lookup for fast validation
    found_codes = {e.code for e in events}
    missing = set(uppercased) - found_codes
    if missing:
        raise ValueError(f"Events not found: {', '.join(sorted(missing))}")

    # Ownership check (when user is provided)
    if user is not None:
        not_owned = [e.code for e in events if e.created_by_user_id != user.id]
        if not_owned:
            raise ValueError(f"Events not found or not owned: {', '.join(sorted(not_owned))}")

    # All validated — delete each event using existing cascade logic
    for event in events:
        delete_event(db, event)

    return len(events)


def archive_event(db: Session, event: Event) -> Event:
    """Archive an event by setting archived_at timestamp."""
    event.archived_at = utcnow()
    db.commit()
    db.refresh(event)
    return event


def unarchive_event(db: Session, event: Event) -> Event:
    """Unarchive an event by clearing archived_at timestamp."""
    event.archived_at = None
    db.commit()
    db.refresh(event)
    return event


def get_archived_events_for_user(db: Session, user: User) -> list[tuple[Event, int]]:
    """
    Get all archived events for a user with request counts.

    Returns:
        List of (event, request_count) tuples for archived events.
    """
    results = (
        db.query(Event, func.count(Request.id).label("request_count"))
        .outerjoin(Request, Request.event_id == Event.id)
        .filter(
            Event.created_by_user_id == user.id,
            Event.archived_at != None,
        )
        .group_by(Event.id)
        .order_by(Event.archived_at.desc())
        .all()
    )
    return [(event, count) for event, count in results]


def get_expired_events_for_user(db: Session, user: User) -> list[tuple[Event, int]]:
    """
    Get all expired (but not archived) events for a user with request counts.

    Returns:
        List of (event, request_count) tuples for expired events.
    """
    results = (
        db.query(Event, func.count(Request.id).label("request_count"))
        .outerjoin(Request, Request.event_id == Event.id)
        .filter(
            Event.created_by_user_id == user.id,
            Event.archived_at == None,
            (Event.expires_at <= utcnow()) | (Event.is_active == False),
        )
        .group_by(Event.id)
        .order_by(Event.expires_at.desc())
        .all()
    )
    return [(event, count) for event, count in results]
