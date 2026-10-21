from datetime import datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user_optional,
    get_db,
    get_owned_event,
    require_verified_human_soft,
)
from app.api.event_status import raise_for_unavailable_event
from app.api.request_mapping import request_to_out as _request_to_out
from app.core.config import get_settings
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.rate_limit import get_guest_id, limiter
from app.models.event import Event
from app.models.request import RequestStatus
from app.models.user import User
from app.schemas.common import AcceptAllResponse, BulkActionResponse
from app.schemas.request import (
    RequestCreate,
    RequestListResponse,
    RequestOut,
    RequestSort,
    SortDirection,
)
from app.services.event import (
    get_event_by_public_code_with_status,
)
from app.services.event_bus import publish_event
from app.services.kiosk import is_trusted_kiosk_for_event
from app.services.request import (
    RequestCreateData,
    accept_all_new_requests,
    bulk_delete_requests,
    create_request,
    reject_all_new_requests,
)
from app.services.request_sort import (
    DEFAULT_SORT_DIRECTION,
    filtered_requests_query,
    get_sorted_requests,
    status_counts,
)
from app.services.sync.orchestrator import (
    enrich_with_fresh_session,
    sync_requests_with_fresh_session,
)
from app.services.sync.registry import get_connected_adapters

router = APIRouter()


@router.post("/{code}/requests", response_model=RequestOut)
@limiter.limit(lambda: f"{get_settings().request_rate_limit_per_minute}/minute")
def submit_request(
    code: str,
    request_data: RequestCreate,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> RequestOut:
    event, lookup_result = get_event_by_public_code_with_status(db, code)

    raise_for_unavailable_event(lookup_result)

    # The authenticated owner (DJ dashboard "Add" button) AND a paired kiosk (a
    # trusted physical device on this event) both bypass the guest
    # human-verification gate. Neither holds a wrzdj_human cookie, so an enforced
    # gate would 403 them — the kiosk submit path included (issue #514). Everyone
    # else still passes through it (soft/enforced).
    is_owner = current_user is not None and current_user.id == event.created_by_user_id
    is_kiosk = is_trusted_kiosk_for_event(db, request.headers.get("X-Kiosk-Session"), event)
    if not is_owner and not is_kiosk:
        require_verified_human_soft(request, response, db)

    if not event.requests_open:
        raise HTTPException(status_code=403, detail="Requests are closed for this event")

    song_request, is_duplicate = create_request(
        db=db,
        event=event,
        data=RequestCreateData(
            artist=request_data.artist,
            title=request_data.title,
            note=request_data.note,
            nickname=request_data.nickname,
            source=request_data.source.value,
            source_url=request_data.source_url,
            artwork_url=request_data.artwork_url,
            guest_id=get_guest_id(request, db),
            raw_search_query=request_data.raw_search_query,
            genre=request_data.genre,
            bpm=request_data.bpm,
            musical_key=request_data.musical_key,
            isrc=request_data.isrc,
        ),
    )

    # Enrich missing metadata in the background (Beatport, MusicBrainz). Enqueue
    # even for already-complete submissions: enrich_request_metadata seeds the
    # master track store and returns fast when the trio is present, so a complete
    # search-result submission still populates the store for reuse (#541). Use a
    # FRESH session (not the request-scoped `db`) so the task — which may make
    # Spotify/Soundcharts network calls — doesn't pin a pool connection (#505).
    if not is_duplicate:
        background_tasks.add_task(enrich_with_fresh_session, song_request.id)

    if not is_duplicate:
        publish_event(
            event.code,  # canonical SSE channel key (matches the stream subscriber)
            "request_created",
            {
                "request_id": song_request.id,
                "title": song_request.song_title,
                "artist": song_request.artist,
            },
        )

    return _request_to_out(song_request).model_copy(update={"is_duplicate": is_duplicate})


@router.post("/{code}/requests/accept-all", response_model=AcceptAllResponse)
@limiter.limit("10/minute")
def accept_all_requests_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> AcceptAllResponse:
    """Accept all NEW requests for an event in one operation."""
    accepted = accept_all_new_requests(db, event)

    # Trigger batch sync — one background task for all accepted requests
    # Uses sequential search + batch playlist add to avoid API rate limiting.
    # Pass IDs (not the request `db` or live rows) so the task uses a fresh,
    # promptly-closed session instead of pinning the pool connection (issue #505).
    if accepted and get_connected_adapters(event.created_by):
        background_tasks.add_task(sync_requests_with_fresh_session, [r.id for r in accepted])

    if accepted:
        publish_event(
            event.code,
            "requests_bulk_update",
            {
                "action": "accepted",
                "count": len(accepted),
            },
        )

    return AcceptAllResponse(status="ok", accepted_count=len(accepted))


@router.post("/{code}/requests/reject-all", response_model=BulkActionResponse)
@limiter.limit("10/minute")
def reject_all_requests_endpoint(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> BulkActionResponse:
    """Reject all NEW requests for an event in one operation."""
    count = reject_all_new_requests(db, event)
    if count > 0:
        publish_event(
            event.code,
            "requests_bulk_update",
            {
                "action": "rejected",
                "count": count,
            },
        )
    return BulkActionResponse(status="ok", count=count)


@router.delete("/{code}/requests/bulk", response_model=BulkActionResponse)
@limiter.limit("10/minute")
def bulk_delete_requests_endpoint(
    request: Request,
    status: str | None = Query(default=None),
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> BulkActionResponse:
    """Bulk delete requests for an event, optionally filtered by status."""
    count = bulk_delete_requests(db, event, status)
    if count > 0:
        publish_event(
            event.code,
            "requests_bulk_update",
            {
                "action": "deleted",
                "count": count,
            },
        )
    return BulkActionResponse(status="ok", count=count)


@router.get("/{code}/requests", response_model=RequestListResponse)
@limiter.limit("60/minute")
def get_event_requests(
    request: Request,
    status: RequestStatus | None = None,
    since: datetime | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    sort: RequestSort = RequestSort.DATE_REQUESTED,
    direction: SortDirection | None = None,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> RequestListResponse:
    """Paginated, sorted request list. Owner sees requests regardless of status.

    ``total`` is computed before pagination so the dashboard shows a truthful
    count rather than inferring it from the returned page length (issue #478).
    """
    resolved = direction or DEFAULT_SORT_DIRECTION[sort]

    if sort == RequestSort.BEST_MATCH:
        requests, total = _best_match_page(db, event, status, since, limit, offset, resolved)
    else:
        rows, total = get_sorted_requests(
            db,
            event,
            status=status,
            since=since,
            sort=sort,
            direction=resolved,
            limit=limit,
            offset=offset,
        )
        requests = [_request_to_out(r) for r in rows]

    return RequestListResponse(
        requests=requests,
        total=total,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=resolved,
        status_counts=status_counts(db, event),
    )


def _best_match_page(
    db: Session,
    event: "Event",
    status: RequestStatus | None,
    since: datetime | None,
    limit: int,
    offset: int,
    direction: SortDirection,
) -> tuple[list[RequestOut], int]:
    """Best Match (priority) sort with a true total, then paginate.

    Priority scoring needs now-playing context and runs over the whole filtered
    set, so we score everything, then slice the requested window. ``_apply_priority_sort``
    ranks highest-score-first (desc); ``asc`` reverses it so the response's
    ``direction`` metadata matches the order actually applied (issue #478).
    """
    base = filtered_requests_query(db, event, status, since)
    total = base.count()
    ordered = _apply_priority_sort(base.all(), event, db)
    if direction == SortDirection.ASC:
        ordered = list(reversed(ordered))
    return ordered[offset : offset + limit], total


def _apply_priority_sort(
    requests: list,
    event: "Event",
    db: Session,
) -> list[RequestOut]:
    """Score and sort requests by DJ priority, attaching scores to output."""
    from app.services.now_playing import get_now_playing
    from app.services.priority_scorer import (
        RequestScoreInput,
        rank_requests_by_priority,
    )

    # Get now-playing context (BPM/key from matched request)
    now_playing_key: str | None = None
    now_playing_bpm: float | None = None
    np = get_now_playing(db, event.id)
    if np and np.matched_request_id:
        matched = np.matched_request
        if matched:
            now_playing_key = matched.musical_key
            now_playing_bpm = matched.bpm

    # Build scoring inputs
    inputs = [
        RequestScoreInput(
            request_id=r.id,
            vote_count=r.vote_count,
            created_at=r.created_at,
            musical_key=r.musical_key,
            bpm=r.bpm,
        )
        for r in requests
    ]

    # Score and rank
    scored = rank_requests_by_priority(
        inputs,
        now_playing_key=now_playing_key,
        now_playing_bpm=now_playing_bpm,
    )

    # Build a lookup for scores by request_id
    score_map = {s.request_id: s.score for s in scored}
    # Build ordered ID list
    ordered_ids = [s.request_id for s in scored]

    # Sort requests to match scored order and attach priority_score
    request_by_id = {r.id: r for r in requests}
    result = []
    for rid in ordered_ids:
        r = request_by_id.get(rid)
        if r:
            out = _request_to_out(r)
            out.priority_score = score_map.get(rid)
            result.append(out)

    return result
