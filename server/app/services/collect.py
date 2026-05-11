"""Service layer for pre-event collection."""

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.request import Request as SongRequest
from app.schemas.collect import BulkReviewRequest, UpdateCollectionSettings


class NicknameConflictError(Exception):
    """Raised when a nickname is already in use by another guest in the event."""

    def __init__(self, claimed: bool) -> None:
        self.claimed = claimed
        super().__init__("nickname_taken")


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize a datetime to naive UTC (tzinfo stripped)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    return dt


def collection_settings_payload(event: Event) -> dict:
    """Serialize collection-scheduling settings for the dashboard."""
    return {
        "collection_opens_at": event.collection_opens_at,
        "live_starts_at": event.live_starts_at,
        "submission_cap_per_guest": event.submission_cap_per_guest,
        "collection_phase_override": event.collection_phase_override,
        "phase": event.phase,
        "tidal_sync_enabled": event.tidal_sync_enabled,
        "tidal_collection_playlist_id": event.tidal_collection_playlist_id,
    }


def update_collection_settings(
    db: Session, event: Event, payload: UpdateCollectionSettings
) -> Event:
    """Apply a collection-settings update and commit.

    Validates that collection_opens_at precedes live_starts_at and auto-extends
    expires_at when the scheduled live phase runs past it (the default 6h event
    expiry is too short for multi-day pre-event collection).
    """
    if payload.collection_opens_at is not None:
        event.collection_opens_at = _to_naive_utc(payload.collection_opens_at)
    if payload.live_starts_at is not None:
        event.live_starts_at = _to_naive_utc(payload.live_starts_at)
    if payload.submission_cap_per_guest is not None:
        event.submission_cap_per_guest = payload.submission_cap_per_guest
    if "collection_phase_override" in payload.model_fields_set:
        event.collection_phase_override = payload.collection_phase_override
    if payload.tidal_sync_enabled is not None:
        event.tidal_sync_enabled = payload.tidal_sync_enabled

    opens = event.collection_opens_at
    live = event.live_starts_at
    expires = event.expires_at
    if opens and live and opens >= live:
        raise HTTPException(
            status_code=400, detail="collection_opens_at must be before live_starts_at"
        )
    if live and expires and live >= expires:
        event.expires_at = live + timedelta(hours=12)

    db.commit()
    db.refresh(event)
    return event


def get_pending_review_rows(db: Session, event_id: int, limit: int = 200) -> list[SongRequest]:
    """Collection-phase requests awaiting DJ review, ranked by votes then age."""
    return (
        db.query(SongRequest)
        .filter(SongRequest.event_id == event_id)
        .filter(SongRequest.submitted_during_collection == True)  # noqa: E712
        .filter(SongRequest.status == "new")
        .order_by(SongRequest.vote_count.desc(), SongRequest.created_at.asc())
        .limit(limit)
        .all()
    )


def execute_bulk_review(
    db: Session, event_id: int, payload: BulkReviewRequest
) -> tuple[int, int, list[SongRequest]]:
    """Apply a bulk-review action to collection-phase pending requests.

    Returns (accepted_count, rejected_count, accepted_rows). Caller is expected
    to pass accepted_rows to sync_requests_batch() as a FastAPI background task
    so the metadata-enrichment + playlist-sync pipeline runs before the tracks
    show up in the DJ queue. Guest-collect submissions don't have BPM/key/genre;
    this is the first chance to fill them in.

    Raises HTTPException(400) when the payload parameters are inconsistent with
    the selected action.
    """
    pending_q = (
        db.query(SongRequest)
        .filter(SongRequest.event_id == event_id)
        .filter(SongRequest.submitted_during_collection == True)  # noqa: E712
        .filter(SongRequest.status == "new")
    )

    accepted = 0
    rejected = 0
    accepted_rows: list[SongRequest] = []

    if payload.action == "accept_top_n":
        if payload.n is None:
            raise HTTPException(status_code=400, detail="n is required")
        rows = (
            pending_q.order_by(SongRequest.vote_count.desc(), SongRequest.created_at.asc())
            .limit(payload.n)
            .all()
        )
        for r in rows:
            r.status = "accepted"
            accepted += 1
            accepted_rows.append(r)
    elif payload.action == "accept_threshold":
        if payload.min_votes is None:
            raise HTTPException(status_code=400, detail="min_votes is required")
        rows = pending_q.filter(SongRequest.vote_count >= payload.min_votes).all()
        for r in rows:
            r.status = "accepted"
            accepted += 1
            accepted_rows.append(r)
    elif payload.action == "accept_ids":
        if not payload.request_ids:
            raise HTTPException(status_code=400, detail="request_ids is required")
        rows = pending_q.filter(SongRequest.id.in_(payload.request_ids)).all()
        for r in rows:
            r.status = "accepted"
            accepted += 1
            accepted_rows.append(r)
    elif payload.action == "reject_ids":
        if not payload.request_ids:
            raise HTTPException(status_code=400, detail="request_ids is required")
        rows = pending_q.filter(SongRequest.id.in_(payload.request_ids)).all()
        for r in rows:
            r.status = "rejected"
            rejected += 1
    elif payload.action == "reject_remaining":
        rows = pending_q.all()
        for r in rows:
            r.status = "rejected"
            rejected += 1

    db.commit()
    return accepted, rejected, accepted_rows


class SubmissionCapExceeded(Exception):
    """Raised when a guest has hit their per-event submission cap."""


def get_profile(
    db: Session,
    *,
    event_id: int,
    guest_id: int | None = None,
) -> GuestProfile | None:
    """Find a profile by guest_id. Returns None when no cookie/guest_id is
    available — there is no IP fallback. See docs/RECOVERY-IP-IDENTITY.md.
    """
    if guest_id is None:
        return None
    return (
        db.query(GuestProfile)
        .filter(GuestProfile.event_id == event_id, GuestProfile.guest_id == guest_id)
        .one_or_none()
    )


def upsert_profile(
    db: Session,
    *,
    event_id: int,
    guest_id: int | None = None,
    nickname: str | None = None,
) -> GuestProfile | None:
    """Create or update a profile keyed on (event_id, guest_id). Returns None
    when no guest_id is provided — anonymous callers cannot persist profile state.

    Raises NicknameConflictError when the requested nickname is already held by
    a different guest in the same event. claimed=True when the owner is email-verified.
    """
    if guest_id is None:
        return None

    if nickname is not None:
        existing = (
            db.query(GuestProfile)
            .filter(
                GuestProfile.event_id == event_id,
                GuestProfile.guest_id != guest_id,
                func.lower(GuestProfile.nickname) == nickname.lower(),
            )
            .first()
        )
        if existing:
            owner = db.get(Guest, existing.guest_id)
            claimed = owner is not None and owner.email_verified_at is not None
            raise NicknameConflictError(claimed=claimed)

    profile = get_profile(db, event_id=event_id, guest_id=guest_id)
    if profile is None:
        profile = GuestProfile(
            event_id=event_id,
            guest_id=guest_id,
            nickname=nickname,
        )
        db.add(profile)
    else:
        if nickname is not None:
            profile.nickname = nickname
    db.commit()
    db.refresh(profile)
    return profile


def check_and_increment_submission_count(
    db: Session,
    *,
    event: Event,
    guest_id: int | None = None,
) -> GuestProfile:
    """Atomically enforce the per-guest cap, incrementing submission_count on success.

    Raises SubmissionCapExceeded when the cap would be exceeded. cap == 0 means
    unlimited (explicit by design). Requires guest_id (cookie identity).
    """
    if guest_id is None:
        raise ValueError("guest_id is required — see docs/RECOVERY-IP-IDENTITY.md")
    profile = get_profile(db, event_id=event.id, guest_id=guest_id)
    if profile is None:
        profile = GuestProfile(
            event_id=event.id,
            guest_id=guest_id,
        )
        db.add(profile)
        db.flush()

    cap = event.submission_cap_per_guest
    if cap != 0 and profile.submission_count >= cap:
        db.rollback()
        raise SubmissionCapExceeded()

    profile.submission_count += 1
    db.commit()
    db.refresh(profile)
    return profile
