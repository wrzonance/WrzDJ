from datetime import datetime

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.services.dedup import compute_dedupe_key, find_duplicate
from app.services.recommendation.camelot import parse_key
from app.services.vote import add_vote

# Valid state transitions for request status
VALID_TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.NEW: {RequestStatus.ACCEPTED, RequestStatus.REJECTED},
    RequestStatus.ACCEPTED: {RequestStatus.PLAYING, RequestStatus.REJECTED},
    RequestStatus.PLAYING: {RequestStatus.PLAYED},
    RequestStatus.REJECTED: {RequestStatus.NEW},
    RequestStatus.PLAYED: set(),
}


class InvalidStatusTransitionError(ValueError):
    """Raised when an invalid status transition is attempted."""


def normalize_key(key_str: str | None) -> str | None:
    """Normalize a musical key to Camelot notation (e.g., '8A', '5B').

    Accepts any format: 'D Minor', 'Dm', 'Eb', 'CSharp', '7A', etc.
    Returns the Camelot code or None if unrecognizable.
    """
    if not key_str:
        return None
    pos = parse_key(key_str)
    return str(pos) if pos else None


def create_request(
    db: Session,
    event: Event,
    artist: str,
    title: str,
    note: str | None = None,
    nickname: str | None = None,
    source: str = "manual",
    source_url: str | None = None,
    artwork_url: str | None = None,
    guest_id: int | None = None,
    raw_search_query: str | None = None,
    genre: str | None = None,
    bpm: float | None = None,
    musical_key: str | None = None,
) -> tuple[Request, bool]:
    """
    Create a new song request.
    Returns (request, is_duplicate).
    """
    dedupe_key = compute_dedupe_key(artist, title)
    existing = find_duplicate(db, event.id, artist, title)

    if existing:
        if guest_id:
            add_vote(db, existing.id, guest_id=guest_id)
            db.refresh(existing)
        return existing, True

    request = Request(
        event_id=event.id,
        song_title=title,
        artist=artist,
        note=note,
        nickname=nickname,
        source=source,
        source_url=source_url,
        artwork_url=artwork_url,
        guest_id=guest_id,
        dedupe_key=dedupe_key,
        raw_search_query=raw_search_query,
        genre=genre,
        bpm=bpm,
        musical_key=normalize_key(musical_key),
        # Flag based on event phase so /join and /collect entry points produce
        # equivalent rows during collection — otherwise /join submissions are
        # invisible in the collect leaderboard despite being valid.
        submitted_during_collection=(event.phase == "collection"),
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request, False


def get_requests_for_event(
    db: Session,
    event: Event,
    status: RequestStatus | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[Request]:
    """Get requests for an event with optional filters."""
    query = db.query(Request).filter(Request.event_id == event.id)

    if status:
        query = query.filter(Request.status == status.value)

    if since:
        query = query.filter(Request.created_at > since)

    return query.order_by(Request.created_at.desc()).limit(limit).all()


def mark_accepted(req: Request, now: datetime) -> None:
    """Record the first time *req* enters ACCEPTED.

    Idempotent and history-preserving: once set, ``accepted_at`` is never moved
    by a re-accept or a later status change (playing/played/rejected), because
    the DJ sort field is *date accepted* — a historical fact, not "currently
    accepted at" (issue #478).
    """
    if req.accepted_at is None:
        req.accepted_at = now


def update_request_status(db: Session, request: Request, status: RequestStatus) -> Request:
    """Update the status of a request.

    Raises:
        InvalidStatusTransitionError: If the transition is not allowed.
    """
    current = RequestStatus(request.status)
    allowed = VALID_TRANSITIONS.get(current, set())
    if status not in allowed:
        raise InvalidStatusTransitionError(
            f"Cannot transition from '{current.value}' to '{status.value}'"
        )
    request.status = status.value
    request.updated_at = utcnow()
    if status == RequestStatus.ACCEPTED:
        mark_accepted(request, request.updated_at)
    db.commit()
    db.refresh(request)
    return request


def clear_other_playing_requests(db: Session, event_id: int, current_request_id: int) -> list[int]:
    """Transition all other PLAYING requests for the event to PLAYED.

    Ensures only one request is in PLAYING status at a time.
    Returns list of request IDs that were transitioned.
    """
    playing_requests = (
        db.query(Request)
        .filter(
            Request.event_id == event_id,
            Request.status == RequestStatus.PLAYING.value,
            Request.id != current_request_id,
        )
        .all()
    )
    now = utcnow()
    cleared_ids = []
    for req in playing_requests:
        req.status = RequestStatus.PLAYED.value
        req.updated_at = now
        cleared_ids.append(req.id)
    if cleared_ids:
        db.commit()
    return cleared_ids


def accept_all_new_requests(db: Session, event: Event) -> list[Request]:
    """Accept all NEW requests for an event in a single transaction."""
    new_requests = (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.status == RequestStatus.NEW.value,
        )
        .all()
    )
    now = utcnow()
    for req in new_requests:
        req.status = RequestStatus.ACCEPTED.value
        req.updated_at = now
        mark_accepted(req, now)
    db.commit()
    for req in new_requests:
        db.refresh(req)
    return new_requests


def get_guest_visible_requests(
    db: Session,
    event: Event,
    limit: int = 50,
) -> list[Request]:
    """Get requests visible to guests (NEW and ACCEPTED only)."""
    return (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.status.in_([RequestStatus.NEW.value, RequestStatus.ACCEPTED.value]),
        )
        .order_by(Request.vote_count.desc(), Request.created_at.desc())
        .limit(limit)
        .all()
    )


def delete_request(db: Session, request: Request) -> None:
    """Delete a request and its associated votes."""
    from app.models.request_vote import RequestVote

    db.query(RequestVote).filter(RequestVote.request_id == request.id).delete()
    db.delete(request)
    db.commit()


def clear_request_metadata(db: Session, request: Request) -> Request:
    """Clear enrichment metadata so it can be re-fetched."""
    request.genre = None
    request.bpm = None
    request.musical_key = None
    db.commit()
    db.refresh(request)
    return request


def reject_all_new_requests(db: Session, event: Event) -> int:
    """Reject all NEW requests for an event. Returns count of rejected requests."""
    new_requests = (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.status == RequestStatus.NEW.value,
        )
        .all()
    )
    now = utcnow()
    for req in new_requests:
        req.status = RequestStatus.REJECTED.value
        req.updated_at = now
    db.commit()
    return len(new_requests)


def bulk_delete_requests(db: Session, event: Event, status: str | None = None) -> int:
    """Bulk delete requests for an event, optionally filtered by status.

    Returns count of deleted requests.
    """
    from app.models.request_vote import RequestVote

    query = db.query(Request).filter(Request.event_id == event.id)
    if status:
        query = query.filter(Request.status == status)

    request_ids = [r.id for r in query.all()]
    if not request_ids:
        return 0

    # Delete votes first (SQLite doesn't enforce FK cascades)
    db.query(RequestVote).filter(RequestVote.request_id.in_(request_ids)).delete(
        synchronize_session=False
    )
    count = db.query(Request).filter(Request.id.in_(request_ids)).delete(synchronize_session=False)
    db.commit()
    return count


def get_requests_by_guest(
    db: Session,
    event_id: int,
    guest_id: int,
    limit: int = 50,
) -> list[Request]:
    """Get all requests submitted by a specific guest for an event."""
    return (
        db.query(Request)
        .filter(
            Request.event_id == event_id,
            Request.guest_id == guest_id,
        )
        .order_by(Request.created_at.desc())
        .limit(limit)
        .all()
    )


def get_request_by_id(db: Session, request_id: int) -> Request | None:
    """Get a request by its ID."""
    return db.query(Request).filter(Request.id == request_id).first()
