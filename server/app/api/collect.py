"""Public API endpoints for pre-event song collection (no authentication required).

Identity is `guest_id` only — the wrzdj_guest cookie is required for write
endpoints. See docs/RECOVERY-IP-IDENTITY.md.
"""

import logging
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_email_verified, require_verified_human
from app.core.rate_limit import limiter
from app.models.event import Event
from app.models.guest import Guest
from app.models.request import Request as SongRequest
from app.models.request import RequestStatus
from app.models.request_vote import RequestVote
from app.schemas.collect import (
    CollectEventPreview,
    CollectLeaderboardResponse,
    CollectLeaderboardRow,
    CollectMyPicksItem,
    CollectMyPicksResponse,
    CollectPreviewResponse,
    CollectProfileRequest,
    CollectProfileResponse,
    CollectSubmitRequest,
    CollectVoteRequest,
    EnrichPreviewItem,  # noqa: F401
    EnrichPreviewRequest,
    EnrichPreviewResponse,
    EnrichPreviewResult,
    LiveJoinCodeResponse,
)
from app.services import collect as collect_service
from app.services.activity_log import log_activity
from app.services.beatport import search_beatport_tracks
from app.services.collect import NicknameConflictError, upsert_profile
from app.services.dedup import compute_dedupe_key, find_duplicate
from app.services.sync.enrichment_pipeline import _find_best_match
from app.services.sync.orchestrator import enrich_request_metadata
from app.services.system_settings import get_system_settings
from app.services.tidal import sync_collection_requests_batch
from app.services.vote import add_vote

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_event_or_404(db: Session, code: str) -> Event:
    event = db.query(Event).filter(Event.code == code).one_or_none()
    if event is None or not event.is_active:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def _banner_url_for_event(event: Event, request: Request) -> str | None:
    """Build a public URL for the event's banner image, or None if not set."""
    if not event.banner_filename:
        return None
    base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https" and base.startswith("http://"):
        base = "https://" + base[len("http://") :]
    return f"{base}/uploads/{event.banner_filename}"


def _banner_colors_for_event(event: Event) -> list[str] | None:
    """Parse the stored JSON-encoded banner_colors string into a list, or None."""
    if not event.banner_colors:
        return None
    import json as _json

    try:
        value = _json.loads(event.banner_colors)
        if isinstance(value, list) and all(isinstance(c, str) for c in value):
            return value
    except (_json.JSONDecodeError, TypeError):
        pass
    return None


@router.get("/{code}", response_model=CollectEventPreview)
@limiter.limit("120/minute")
def preview(code: str, request: Request, db: Session = Depends(get_db)):
    event = _get_event_or_404(db, code)
    settings = get_system_settings(db)
    return CollectEventPreview(
        code=event.code,
        name=event.name,
        banner_filename=event.banner_filename,
        banner_url=_banner_url_for_event(event, request),
        banner_colors=_banner_colors_for_event(event),
        submission_cap_per_guest=event.submission_cap_per_guest,
        registration_enabled=settings.registration_enabled,
        phase=event.phase,
        collection_opens_at=event.collection_opens_at,
        live_starts_at=event.live_starts_at,
        expires_at=event.expires_at,
    )


@router.get("/{code}/leaderboard", response_model=CollectLeaderboardResponse)
@limiter.limit("120/minute")
def leaderboard(
    code: str,
    request: Request,
    tab: Literal["trending", "all"] = "trending",
    db: Session = Depends(get_db),
):
    event = _get_event_or_404(db, code)

    q = (
        db.query(SongRequest, Guest.email_verified_at)
        .outerjoin(Guest, SongRequest.guest_id == Guest.id)
        .filter(SongRequest.event_id == event.id)
        .filter(SongRequest.submitted_during_collection == True)  # noqa: E712
    )
    if tab == "trending":
        q = q.filter(SongRequest.vote_count >= 1).order_by(
            SongRequest.vote_count.desc(), SongRequest.created_at.desc()
        )
    else:
        # "All" is the discovery view — alphabetical makes it easy to scan
        # and upvote existing submissions rather than recency bias.
        q = q.order_by(func.lower(SongRequest.song_title).asc())

    rows = q.limit(200).all()
    return CollectLeaderboardResponse(
        requests=[
            CollectLeaderboardRow(
                id=r.id,
                title=r.song_title,
                artist=r.artist,
                artwork_url=r.artwork_url,
                vote_count=r.vote_count,
                nickname=r.nickname,
                status=r.status,
                created_at=r.created_at,
                bpm=int(r.bpm) if r.bpm is not None else None,
                musical_key=r.musical_key,
                genre=r.genre,
                requester_verified=email_verified_at is not None,
            )
            for r, email_verified_at in rows
        ],
        total=len(rows),
    )


@router.get("/{code}/profile", response_model=CollectProfileResponse)
@limiter.limit("60/minute")
def get_profile(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    guest_id: int = Depends(require_verified_human),
):
    event = _get_event_or_404(db, code)
    profile = collect_service.get_profile(db, event_id=event.id, guest_id=guest_id)
    from app.models.guest import Guest

    guest_row = db.query(Guest).filter(Guest.id == guest_id).first()
    is_verified = guest_row is not None and guest_row.email_verified_at is not None
    if profile is None:
        return CollectProfileResponse(
            nickname=None,
            email_verified=is_verified,
            submission_count=0,
            submission_cap=event.submission_cap_per_guest,
        )
    return CollectProfileResponse(
        nickname=profile.nickname,
        email_verified=is_verified,
        submission_count=profile.submission_count,
        submission_cap=event.submission_cap_per_guest,
    )


@router.post("/{code}/profile", response_model=CollectProfileResponse)
@limiter.limit("5/minute")
def set_profile(
    code: str,
    payload: CollectProfileRequest,
    request: Request,
    db: Session = Depends(get_db),
    guest_id: int = Depends(require_email_verified),
):
    event = _get_event_or_404(db, code)
    try:
        profile = upsert_profile(
            db,
            event_id=event.id,
            guest_id=guest_id,
            nickname=payload.nickname,
        )
    except NicknameConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "nickname_taken", "claimed": exc.claimed},
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "nickname_taken", "claimed": False},
        )
    if payload.nickname is not None:
        log_activity(
            db,
            level="info",
            source="collect",
            message=f"Guest #{guest_id} updated profile: nickname",
            event_code=code,
        )
    is_verified = False
    from app.models.guest import Guest

    guest_row = db.query(Guest).filter(Guest.id == guest_id).first()
    is_verified = guest_row is not None and guest_row.email_verified_at is not None
    return CollectProfileResponse(
        nickname=profile.nickname if profile is not None else payload.nickname,
        email_verified=is_verified,
        submission_count=profile.submission_count if profile is not None else 0,
        submission_cap=event.submission_cap_per_guest,
    )


@router.get("/{code}/profile/me", response_model=CollectMyPicksResponse)
@limiter.limit("60/minute")
def my_picks(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    guest_id: int = Depends(require_email_verified),
):
    event = _get_event_or_404(db, code)

    submitted = (
        db.query(SongRequest)
        .filter(SongRequest.event_id == event.id)
        .filter(SongRequest.submitted_during_collection == True)  # noqa: E712
        .filter(SongRequest.guest_id == guest_id)
        .order_by(SongRequest.created_at.desc())
        .all()
    )

    voted_rows = (
        db.query(RequestVote.request_id)
        .join(SongRequest, SongRequest.id == RequestVote.request_id)
        .filter(RequestVote.guest_id == guest_id)
        .filter(SongRequest.event_id == event.id)
        .all()
    )
    upvoted_request_ids = [row[0] for row in voted_rows]
    upvoted: list[SongRequest] = []
    if upvoted_request_ids:
        upvoted = (
            db.query(SongRequest)
            .filter(SongRequest.event_id == event.id)
            .filter(SongRequest.id.in_(upvoted_request_ids))
            .filter(SongRequest.submitted_during_collection == True)  # noqa: E712
            .all()
        )

    top_row = (
        db.query(
            SongRequest.guest_id,
            func.count(SongRequest.id).label("n"),
        )
        .filter(SongRequest.event_id == event.id)
        .filter(SongRequest.submitted_during_collection == True)  # noqa: E712
        .filter(SongRequest.guest_id.isnot(None))
        .group_by(SongRequest.guest_id)
        .order_by(desc("n"))
        .first()
    )
    is_top = top_row is not None and top_row[0] == guest_id and top_row[1] > 0

    # First-to-suggest: among submitted rows, the ones where no earlier row in the
    # event shares the same dedupe_key.
    first_suggestion_ids: list[int] = []
    for r in submitted:
        earlier = (
            db.query(SongRequest.id)
            .filter(SongRequest.event_id == event.id)
            .filter(SongRequest.dedupe_key == r.dedupe_key)
            .filter(SongRequest.created_at < r.created_at)
            .first()
        )
        if earlier is None:
            first_suggestion_ids.append(r.id)

    def _to_row(r: SongRequest, interaction: str) -> CollectMyPicksItem:
        return CollectMyPicksItem(
            id=r.id,
            title=r.song_title,
            artist=r.artist,
            artwork_url=r.artwork_url,
            vote_count=r.vote_count,
            nickname=r.nickname,
            status=r.status,
            created_at=r.created_at,
            interaction=interaction,
            bpm=int(r.bpm) if r.bpm is not None else None,
            musical_key=r.musical_key,
            genre=r.genre,
        )

    submitted_ids = {s.id for s in submitted}
    return CollectMyPicksResponse(
        submitted=[_to_row(r, "submitted") for r in submitted],
        upvoted=[_to_row(r, "upvoted") for r in upvoted if r.id not in submitted_ids],
        is_top_contributor=is_top,
        first_suggestion_ids=first_suggestion_ids,
        voted_request_ids=upvoted_request_ids,
    )


@router.post("/{code}/requests", status_code=201)
@limiter.limit("10/minute")
def submit(
    code: str,
    payload: CollectSubmitRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    guest_id: int = Depends(require_email_verified),
):
    event = _get_event_or_404(db, code)
    if event.phase != "collection":
        raise HTTPException(status_code=409, detail="Collection has ended")

    existing = find_duplicate(db, event.id, payload.artist, payload.song_title)
    if existing:
        is_own = existing.guest_id == guest_id
        if is_own:
            raise HTTPException(status_code=409, detail="You already picked this one!")

        add_vote(db, existing.id, guest_id=guest_id)
        log_activity(
            db,
            level="info",
            source="collect",
            message=(
                f"Guest #{guest_id} duplicate-voted "
                f"'{existing.song_title}' by {existing.artist} (req #{existing.id})"
            ),
            event_code=code,
        )
        return JSONResponse({"id": existing.id, "is_duplicate": True}, status_code=200)

    try:
        collect_service.check_and_increment_submission_count(db, event=event, guest_id=guest_id)
    except collect_service.SubmissionCapExceeded:
        raise HTTPException(status_code=429, detail="Picks limit reached") from None

    if payload.nickname:
        collect_service.upsert_profile(
            db,
            event_id=event.id,
            guest_id=guest_id,
            nickname=payload.nickname,
        )

    row = SongRequest(
        event_id=event.id,
        song_title=payload.song_title,
        artist=payload.artist,
        source=payload.source,
        source_url=payload.source_url,
        artwork_url=payload.artwork_url,
        note=payload.note,
        nickname=payload.nickname,
        status=RequestStatus.NEW.value,
        dedupe_key=compute_dedupe_key(payload.artist, payload.song_title),
        guest_id=guest_id,
        submitted_during_collection=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if not (row.genre and row.bpm and row.musical_key):
        background_tasks.add_task(enrich_request_metadata, db, row.id)
    if event.tidal_sync_enabled and get_system_settings(db).tidal_enabled:
        background_tasks.add_task(
            sync_collection_requests_batch, db, event.created_by, event, [row]
        )
    log_activity(
        db,
        level="info",
        source="collect",
        message=(f"Guest #{guest_id} submitted '{row.song_title}' by {row.artist} (req #{row.id})"),
        event_code=code,
    )
    return {"id": row.id, "is_duplicate": False}


@router.post("/{code}/vote")
@limiter.limit("60/minute")
def vote(
    code: str,
    payload: CollectVoteRequest,
    request: Request,
    db: Session = Depends(get_db),
    guest_id: int = Depends(require_email_verified),
):
    event = _get_event_or_404(db, code)
    if event.phase not in ("collection", "live"):
        raise HTTPException(status_code=409, detail="Voting is closed")
    row = (
        db.query(SongRequest)
        .filter(SongRequest.id == payload.request_id)
        .filter(SongRequest.event_id == event.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if row.guest_id == guest_id:
        raise HTTPException(status_code=409, detail="Can't vote on your own pick")
    _, is_new_vote = add_vote(db, request_id=row.id, guest_id=guest_id)
    if is_new_vote:
        log_activity(
            db,
            level="info",
            source="collect",
            message=(f"Guest #{guest_id} voted on '{row.song_title}' (req #{row.id})"),
            event_code=code,
        )
    return {"ok": True}


@router.post("/{code}/enrich-preview", response_model=EnrichPreviewResponse)
@limiter.limit("10/minute")
def enrich_preview(
    code: str,
    payload: EnrichPreviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    _verified: int = Depends(require_email_verified),
) -> EnrichPreviewResponse:
    """Lightweight Beatport BPM/key lookup for search-time vibes — no DB writes."""
    event = _get_event_or_404(db, code)
    user = event.created_by
    items = payload.items[:10]
    results: list[EnrichPreviewResult] = []

    for item in items:
        bpm = None
        key = None
        genre = None

        if user and user.beatport_access_token:
            try:
                matches = search_beatport_tracks(db, user, f"{item.artist} {item.title}", limit=5)
                if matches:
                    best = _find_best_match(matches, item.title, item.artist)
                    if best:
                        bpm = int(best.bpm) if best.bpm is not None else None
                        key = best.key or None
                        genre = best.genre or None
            except Exception as exc:
                logger.warning(
                    "enrich_preview: Beatport lookup failed for '%s' by '%s': %s",
                    item.title,
                    item.artist,
                    exc,
                )  # nosec B110 — best-effort, callers handle null fields

        results.append(
            EnrichPreviewResult(
                title=item.title,
                artist=item.artist,
                bpm=bpm,
                key=key,
                genre=genre,
            )
        )

    return EnrichPreviewResponse(results=results)


@router.get(
    "/{code}/requests/{request_id}/preview",
    response_model=CollectPreviewResponse,
)
@limiter.limit("10/minute")
def request_preview(
    code: str,
    request_id: int,
    request: Request,
    _verified: int = Depends(require_email_verified),
    db: Session = Depends(get_db),
):
    event = _get_event_or_404(db, code)
    song_request = (
        db.query(SongRequest)
        .filter(SongRequest.id == request_id, SongRequest.event_id == event.id)
        .one_or_none()
    )
    if song_request is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return CollectPreviewResponse(
        source=song_request.source,
        source_url=song_request.source_url,
    )


@router.get("/{code}/live-join-code", response_model=LiveJoinCodeResponse)
@limiter.limit("60/minute")
def get_live_join_code(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    _guest_id: int = Depends(require_verified_human),
) -> LiveJoinCodeResponse:
    """Return the live join_code for an event that has entered the live phase.

    Requires a verified human cookie (not email verification) so the join_code
    is never leaked to unverified bots scraping /collect during the
    collection-to-live transition. The join_code is otherwise revealed only
    via the QR code at the event venue.
    """
    event = _get_event_or_404(db, code)
    if event.phase not in ("live", "closed"):
        raise HTTPException(status_code=409, detail="Event is not live")
    return LiveJoinCodeResponse(join_code=event.join_code)
