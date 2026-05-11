import json
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_db,
    get_event_for_dj_or_admin,
    get_owned_event,
    require_verified_human_soft,
)
from app.core.config import get_settings
from app.core.rate_limit import get_guest_id, limiter
from app.models.event import Event
from app.models.request import RequestStatus
from app.models.user import User
from app.schemas.activity_log import ActivityLogEntry
from app.schemas.collect import (
    BulkReviewRequest,
    BulkReviewResponse,
    PendingReviewResponse,
    PendingReviewRow,
    UpdateCollectionSettings,
)
from app.schemas.common import AcceptAllResponse, BulkActionResponse
from app.schemas.event import (
    BulkDeleteEventsRequest,
    DisplaySettingsResponse,
    DisplaySettingsUpdate,
    EventCreate,
    EventOut,
    EventUpdate,
)
from app.schemas.recommendation import (
    EventMusicProfile,
    LLMPromptRequest,
    RecommendationResponse,
    RecommendedTrack,
    TemplatePlaylistRequest,
)
from app.schemas.request import RequestCreate, RequestOut
from app.schemas.search import SearchResult
from app.services.collect import (
    collection_settings_payload,
    execute_bulk_review,
    get_pending_review_rows,
    update_collection_settings,
)
from app.services.event import (
    EventLookupResult,
    archive_event,
    bulk_delete_events,
    compute_event_status,
    create_event,
    delete_event,
    get_archived_events_for_user,
    get_event_by_code_with_status,
    get_events_for_user,
    get_expired_events_for_user,
    unarchive_event,
    update_event,
)
from app.services.event_bus import publish_event
from app.services.export import (
    export_play_history_to_csv,
    export_requests_to_csv,
    generate_export_filename,
    generate_play_history_export_filename,
)
from app.services.now_playing import (
    get_manual_hide_setting,
    get_play_history,
    set_now_playing_visibility,
)
from app.services.request import (
    accept_all_new_requests,
    bulk_delete_requests,
    create_request,
    get_requests_for_event,
    reject_all_new_requests,
)
from app.services.sync.orchestrator import enrich_request_metadata, sync_requests_batch
from app.services.sync.registry import get_connected_adapters
from app.services.tidal import sync_collection_requests_batch

router = APIRouter()


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize an incoming datetime to naive UTC (matches the project's stored convention).

    Frontend sends ISO strings with timezone (`Z` suffix), which Pydantic parses as
    aware datetimes. The DB columns are naive; comparing aware to naive raises
    TypeError. Strip tz to UTC-naive for storage.
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


settings = get_settings()

# FIXME: per-process cache — value drifts in multi-worker deployments until next request
_llm_rate_limit_cache: dict[str, int] = {"value": 3}

# Maximum number of requests to export in a single CSV
# Set to 10,000 to prevent memory issues and excessive download times
MAX_EXPORT_REQUESTS = 10000

# Maximum number of play history entries to export in a single CSV
MAX_EXPORT_PLAY_HISTORY = 10000


def _content_disposition(filename: str) -> str:
    """Build an RFC 6266 Content-Disposition header value for a download."""
    safe_filename = filename.replace('"', '\\"')
    ascii_filename = quote(filename, safe="")
    return f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{ascii_filename}"


def _get_base_url(request: Request | None) -> str | None:
    """Get the base URL for constructing public URLs."""
    if settings.public_url:
        return settings.public_url.rstrip("/")
    if request:
        return str(request.base_url).rstrip("/")
    return None


def _get_api_base_url(request: Request) -> str:
    """Get the API server's own base URL for constructing asset URLs (uploads, etc.)."""
    base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https" and base.startswith("http://"):
        base = "https://" + base[len("http://") :]
    return base


def _get_banner_urls(event, request: Request | None) -> tuple[str | None, str | None]:
    """Get banner and kiosk banner URLs for an event."""
    if not event.banner_filename:
        return None, None
    if not request:
        return None, None
    api_base = _get_api_base_url(request)
    banner_url = f"{api_base}/uploads/{event.banner_filename}"
    stem = event.banner_filename.rsplit(".", 1)[0]
    kiosk_url = f"{api_base}/uploads/{stem}_kiosk.webp"
    return banner_url, kiosk_url


def _request_to_out(r) -> RequestOut:
    """Convert a Request model to RequestOut schema."""
    return RequestOut(
        id=r.id,
        event_id=r.event_id,
        song_title=r.song_title,
        artist=r.artist,
        source=r.source,
        source_url=r.source_url,
        artwork_url=r.artwork_url,
        note=r.note,
        nickname=r.nickname,
        status=r.status,
        created_at=r.created_at,
        updated_at=r.updated_at,
        raw_search_query=r.raw_search_query,
        sync_results_json=r.sync_results_json,
        vote_count=r.vote_count,
        genre=r.genre,
        bpm=r.bpm,
        musical_key=r.musical_key,
    )


def _build_recommendation_response(result, db) -> RecommendationResponse:
    """Build a RecommendationResponse from a recommendation engine result."""
    from app.services.recommendation.camelot import parse_key
    from app.services.recommendation.llm_hooks import is_llm_available

    profile = EventMusicProfile(
        avg_bpm=result.event_profile.avg_bpm,
        bpm_range_low=result.event_profile.bpm_range[0] if result.event_profile.bpm_range else None,
        bpm_range_high=result.event_profile.bpm_range[1]
        if result.event_profile.bpm_range
        else None,
        dominant_keys=[str(p) for k in result.event_profile.dominant_keys if (p := parse_key(k))],
        dominant_genres=list(result.event_profile.dominant_genres),
        track_count=result.event_profile.track_count,
        enriched_count=result.enriched_count,
    )

    suggestions = [
        RecommendedTrack(
            title=s.profile.title,
            artist=s.profile.artist,
            bpm=s.profile.bpm,
            key=str(p) if (p := parse_key(s.profile.key)) else s.profile.key,
            genre=s.profile.genre,
            score=s.score,
            bpm_score=s.bpm_score,
            key_score=s.key_score,
            genre_score=s.genre_score,
            source=s.profile.source,
            track_id=s.profile.track_id,
            url=s.profile.url,
            cover_url=s.profile.cover_url,
            duration_seconds=s.profile.duration_seconds,
            mb_verified=result.mb_verified.get(s.profile.artist, False),
        )
        for s in result.suggestions
    ]

    return RecommendationResponse(
        suggestions=suggestions,
        profile=profile,
        services_used=result.services_used,
        total_candidates_searched=result.total_candidates_searched,
        llm_available=is_llm_available(db),
    )


def _event_to_out(
    event,
    request: Request | None = None,
    request_count: int | None = None,
    include_status: bool = False,
) -> EventOut:
    """Convert Event model to EventOut schema with join_url."""
    base_url = _get_base_url(request)
    join_url = f"{base_url}/join/{event.code}" if base_url else None

    event_status = compute_event_status(event) if include_status else None

    banner_url, banner_kiosk_url = _get_banner_urls(event, request)
    try:
        banner_colors = json.loads(event.banner_colors) if event.banner_colors else None
    except (json.JSONDecodeError, TypeError):
        banner_colors = None

    return EventOut(
        id=event.id,
        code=event.code,
        name=event.name,
        created_at=event.created_at,
        expires_at=event.expires_at,
        is_active=event.is_active,
        archived_at=event.archived_at,
        status=event_status,
        join_url=join_url,
        request_count=request_count,
        tidal_sync_enabled=event.tidal_sync_enabled,
        tidal_playlist_id=event.tidal_playlist_id,
        beatport_sync_enabled=event.beatport_sync_enabled,
        beatport_playlist_id=event.beatport_playlist_id,
        banner_url=banner_url,
        banner_kiosk_url=banner_kiosk_url,
        banner_colors=banner_colors,
        requests_open=event.requests_open,
        collection_opens_at=event.collection_opens_at,
        live_starts_at=event.live_starts_at,
        submission_cap_per_guest=event.submission_cap_per_guest,
        collection_phase_override=event.collection_phase_override,
    )


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def create_new_event(
    event_data: EventCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EventOut:
    event = create_event(db, event_data.name, current_user, event_data.expires_hours)
    return _event_to_out(event, request)


@router.get("", response_model=list[EventOut])
@limiter.limit("60/minute")
def list_events(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[EventOut]:
    events = get_events_for_user(db, current_user)
    return [_event_to_out(e, request) for e in events]


@router.get("/archived", response_model=list[EventOut])
@limiter.limit("60/minute")
def list_archived_events(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[EventOut]:
    """List all archived and expired events for the current user."""
    # Get archived events
    archived = get_archived_events_for_user(db, current_user)
    # Get expired (but not archived) events
    expired = get_expired_events_for_user(db, current_user)

    # Combine and convert to EventOut with status and request_count
    result = []
    for event, count in archived:
        result.append(_event_to_out(event, request, request_count=count, include_status=True))
    for event, count in expired:
        result.append(_event_to_out(event, request, request_count=count, include_status=True))

    return result


@router.get("/activity", response_model=list[ActivityLogEntry])
@limiter.limit("60/minute")
def get_activity_log(
    request: Request,
    event_code: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get recent activity log entries for the current user's events."""
    from app.services.activity_log import get_recent_activity

    entries = get_recent_activity(db, limit=limit, event_code=event_code, user_id=current_user.id)
    return [
        ActivityLogEntry(
            id=e.id,
            created_at=e.created_at.isoformat(),
            level=e.level,
            source=e.source,
            message=e.message,
            event_code=e.event_code,
        )
        for e in entries
    ]


@router.get("/{code}", response_model=EventOut)
@limiter.limit("60/minute")
def get_event(code: str, request: Request, db: Session = Depends(get_db)) -> EventOut:
    event, lookup_result = get_event_by_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")

    if lookup_result == EventLookupResult.EXPIRED:
        raise HTTPException(status_code=410, detail="Event has expired")

    if lookup_result == EventLookupResult.ARCHIVED:
        raise HTTPException(status_code=410, detail="Event has been archived")

    return _event_to_out(event, request)


@router.get("/{code}/search", response_model=list[SearchResult])
@limiter.limit(lambda: f"{settings.search_rate_limit_per_minute}/minute")
def event_search(
    code: str,
    request: Request,
    q: str = Query(..., min_length=2, max_length=200),
    db: Session = Depends(get_db),
    _human: int | None = Depends(require_verified_human_soft),
) -> list[SearchResult]:
    """Public search endpoint for event guests.

    Priority: Tidal (primary) → Spotify (fallback) → Beatport (event toggle).
    Results are filtered for junk, deduplicated by ISRC, and sorted by popularity.
    """
    from app.services.beatport import search_beatport_tracks
    from app.services.intent_parser import parse_intent
    from app.services.search_merge import build_search_results
    from app.services.spotify import search_songs
    from app.services.system_settings import get_system_settings
    from app.services.tidal import search_tidal_tracks

    event_obj, lookup_result = get_event_by_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")

    if lookup_result in (EventLookupResult.EXPIRED, EventLookupResult.ARCHIVED):
        raise HTTPException(status_code=410, detail="Event has expired")

    sys_settings = get_system_settings(db)
    owner = event_obj.created_by
    intent = parse_intent(q)

    # Tidal primary: search if owner has Tidal linked
    tidal_results = []
    if owner and owner.tidal_access_token:
        tidal_results = search_tidal_tracks(db, owner, q, limit=20)

    # Spotify fallback: only if Tidal returned nothing AND Spotify is enabled
    spotify_results = []
    if not tidal_results and sys_settings.spotify_enabled:
        spotify_results = search_songs(db, q)

    # Beatport append: if owner has it linked and sync enabled for this event
    beatport_results = []
    if (
        sys_settings.beatport_enabled
        and owner
        and owner.beatport_access_token
        and event_obj.beatport_sync_enabled
    ):
        beatport_results = search_beatport_tracks(db, owner, q, limit=10)

    has_any_source = (
        (owner and owner.tidal_access_token)
        or sys_settings.spotify_enabled
        or sys_settings.beatport_enabled
    )
    if not has_any_source:
        raise HTTPException(status_code=503, detail="Song search is currently unavailable")

    return build_search_results(
        tidal_results=tidal_results or None,
        spotify_results=spotify_results or None,
        beatport_results=beatport_results or None,
        intent=intent,
    )


@router.patch("/{code}", response_model=EventOut)
@limiter.limit("20/minute")
def update_event_endpoint(
    event_data: EventUpdate,
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> EventOut:
    updated = update_event(
        db,
        event,
        name=event_data.name,
        expires_at=event_data.expires_at,
    )
    return _event_to_out(updated, request)


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
def delete_event_endpoint(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> None:
    """Delete an event and all its requests."""
    delete_event(db, event)


@router.post("/bulk-delete", response_model=BulkActionResponse)
@limiter.limit("5/minute")
def bulk_delete_events_endpoint(
    request: Request,
    body: BulkDeleteEventsRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> BulkActionResponse:
    """Bulk delete multiple events owned by the current user."""
    try:
        count = bulk_delete_events(db, body.codes, user=current_user)
    except ValueError:
        raise HTTPException(status_code=404, detail="One or more events not found")
    return BulkActionResponse(status="ok", count=count)


@router.post("/{code}/archive", response_model=EventOut)
@limiter.limit("10/minute")
def archive_event_endpoint(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> EventOut:
    """Archive an event."""
    if event.archived_at is not None:
        raise HTTPException(status_code=400, detail="Event is already archived")

    archived = archive_event(db, event)
    return _event_to_out(archived, request, include_status=True)


@router.post("/{code}/unarchive", response_model=EventOut)
@limiter.limit("10/minute")
def unarchive_event_endpoint(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> EventOut:
    """Unarchive an event."""
    if event.archived_at is None:
        raise HTTPException(status_code=400, detail="Event is not archived")

    unarchived = unarchive_event(db, event)
    return _event_to_out(unarchived, request, include_status=True)


@router.patch("/{code}/display-settings", response_model=DisplaySettingsResponse)
def update_display_settings(
    settings: DisplaySettingsUpdate,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> DisplaySettingsResponse:
    """Update display settings for an event (e.g., hide/show now playing on kiosk)."""
    if settings.now_playing_hidden is not None:
        set_now_playing_visibility(db, event.id, settings.now_playing_hidden)

    if settings.now_playing_auto_hide_minutes is not None:
        event.now_playing_auto_hide_minutes = settings.now_playing_auto_hide_minutes

    if settings.requests_open is not None:
        event.requests_open = settings.requests_open

    if settings.kiosk_display_only is not None:
        event.kiosk_display_only = settings.kiosk_display_only

    db.commit()

    hidden = get_manual_hide_setting(db, event.id)
    return DisplaySettingsResponse(
        status="ok",
        now_playing_hidden=hidden,
        now_playing_auto_hide_minutes=event.now_playing_auto_hide_minutes,
        requests_open=event.requests_open,
        kiosk_display_only=event.kiosk_display_only,
    )


@router.get("/{code}/display-settings", response_model=DisplaySettingsResponse)
def get_display_settings(
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> DisplaySettingsResponse:
    """Get current display settings for an event."""
    hidden = get_manual_hide_setting(db, event.id)

    return DisplaySettingsResponse(
        status="ok",
        now_playing_hidden=hidden,
        now_playing_auto_hide_minutes=event.now_playing_auto_hide_minutes,
        requests_open=event.requests_open,
        kiosk_display_only=event.kiosk_display_only,
    )


@router.get("/{code}/export/csv")
@limiter.limit("5/minute")
def export_event_csv(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export event requests as CSV. Owner can export regardless of event status."""
    # Get all requests for the event (no status filter, limited for safety)
    requests = get_requests_for_event(db, event, status=None, since=None, limit=MAX_EXPORT_REQUESTS)

    # Generate CSV content
    csv_content = export_requests_to_csv(event, requests)
    filename = generate_export_filename(event)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/{code}/export/play-history/csv")
@limiter.limit("5/minute")
def export_play_history_csv(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export play history as CSV. Owner can export regardless of event status."""
    # Get all play history entries for the event (limited for safety)
    history_items, _ = get_play_history(db, event.id, limit=MAX_EXPORT_PLAY_HISTORY, offset=0)

    # Generate CSV content
    csv_content = export_play_history_to_csv(event, history_items)
    filename = generate_play_history_export_filename(event)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.post("/{code}/requests", response_model=RequestOut)
@limiter.limit(lambda: f"{settings.request_rate_limit_per_minute}/minute")
def submit_request(
    code: str,
    request_data: RequestCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _human: int | None = Depends(require_verified_human_soft),
) -> RequestOut:
    event, lookup_result = get_event_by_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")

    if lookup_result == EventLookupResult.EXPIRED:
        raise HTTPException(status_code=410, detail="Event has expired")

    if lookup_result == EventLookupResult.ARCHIVED:
        raise HTTPException(status_code=410, detail="Event has been archived")

    if not event.requests_open:
        raise HTTPException(status_code=403, detail="Requests are closed for this event")

    song_request, is_duplicate = create_request(
        db=db,
        event=event,
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
    )

    # Enrich missing metadata in background (Beatport, MusicBrainz)
    has_full_metadata = song_request.genre and song_request.bpm and song_request.musical_key
    if not is_duplicate and not has_full_metadata:
        background_tasks.add_task(enrich_request_metadata, db, song_request.id)

    if not is_duplicate:
        publish_event(
            code,
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
    # Uses sequential search + batch playlist add to avoid API rate limiting
    if accepted and get_connected_adapters(event.created_by):
        background_tasks.add_task(sync_requests_batch, db, accepted)

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


@router.get("/{code}/requests", response_model=list[RequestOut])
@limiter.limit("60/minute")
def get_event_requests(
    request: Request,
    status: RequestStatus | None = None,
    since: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    sort: Literal["chronological", "priority"] = "chronological",
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> list[RequestOut]:
    # Owner can view requests regardless of event status
    requests = get_requests_for_event(db, event, status, since, limit)

    if sort == "priority":
        return _apply_priority_sort(requests, event, db)

    return [_request_to_out(r) for r in requests]


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


@router.post("/{code}/recommendations", response_model=RecommendationResponse)
@limiter.limit("5/minute")
def get_recommendations(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    """Generate song recommendations based on the event's musical profile."""
    from app.services.recommendation.service import generate_recommendations

    user = event.created_by

    # Check if any music services are connected
    has_services = bool(user.tidal_access_token) or bool(user.beatport_access_token)
    if not has_services:
        raise HTTPException(
            status_code=503,
            detail="No music services connected. Link Tidal or Beatport to get recommendations.",
        )

    result = generate_recommendations(db, user, event)
    return _build_recommendation_response(result, db)


@router.get("/{code}/playlists")
@limiter.limit("10/minute")
def get_playlists(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
):
    """List the DJ's playlists from connected music services."""
    from app.schemas.recommendation import PlaylistInfo, PlaylistListResponse

    user = event.created_by
    playlists: list[PlaylistInfo] = []

    if user.tidal_access_token:
        from app.services.tidal import list_user_playlists as tidal_list

        for p in tidal_list(db, user):
            playlists.append(
                PlaylistInfo(
                    id=p.id,
                    name=p.name,
                    num_tracks=p.num_tracks,
                    description=p.description,
                    cover_url=p.cover_url,
                    source=p.source,
                )
            )

    if user.beatport_access_token:
        from app.services.beatport import list_user_playlists as bp_list

        for p in bp_list(db, user):
            playlists.append(
                PlaylistInfo(
                    id=p.id,
                    name=p.name,
                    num_tracks=p.num_tracks,
                    description=p.description,
                    cover_url=p.cover_url,
                    source=p.source,
                )
            )

    return PlaylistListResponse(playlists=playlists)


@router.post("/{code}/recommendations/from-template", response_model=RecommendationResponse)
@limiter.limit("5/minute")
def get_recommendations_from_template(
    request: Request,
    template_request: TemplatePlaylistRequest,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    """Generate recommendations using a template playlist."""
    from app.services.recommendation.service import generate_recommendations_from_template

    user = event.created_by

    # Check if any music services are connected
    has_services = bool(user.tidal_access_token) or bool(user.beatport_access_token)
    if not has_services:
        raise HTTPException(
            status_code=503,
            detail="No music services connected. Link Tidal or Beatport to get recommendations.",
        )

    result = generate_recommendations_from_template(
        db,
        user,
        event,
        template_source=template_request.source,
        template_id=template_request.playlist_id,
    )
    return _build_recommendation_response(result, db)


@router.post("/{code}/recommendations/llm")
@limiter.limit(lambda: f"{_llm_rate_limit_cache['value']}/minute")
async def get_llm_recommendations(
    request: Request,
    prompt_request: LLMPromptRequest,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
):
    """Generate song recommendations from an LLM-interpreted DJ prompt."""
    from app.schemas.recommendation import LLMQueryInfo, LLMRecommendationResponse
    from app.services.recommendation.llm_hooks import is_llm_available
    from app.services.recommendation.service import generate_recommendations_from_llm
    from app.services.system_settings import get_system_settings

    # Refresh LLM rate limit cache from DB
    sys_settings = get_system_settings(db)
    _llm_rate_limit_cache["value"] = sys_settings.llm_rate_limit_per_minute

    if not is_llm_available(db):
        raise HTTPException(
            status_code=503,
            detail="LLM recommendations not configured. Set ANTHROPIC_API_KEY to enable.",
        )

    user = event.created_by

    has_services = bool(user.tidal_access_token) or bool(user.beatport_access_token)
    if not has_services:
        raise HTTPException(
            status_code=503,
            detail="No music services connected. Link Tidal or Beatport to get recommendations.",
        )

    try:
        result = await generate_recommendations_from_llm(db, user, event, prompt_request.prompt)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("LLM recommendation failed")
        raise HTTPException(
            status_code=502,
            detail="LLM service error. Try again or use algorithmic recommendations.",
        )

    base = _build_recommendation_response(result, db)

    llm_queries = [
        LLMQueryInfo(
            search_query=q.search_query,
            target_bpm=q.target_bpm,
            target_key=q.target_key,
            target_genre=q.target_genre,
            reasoning=q.reasoning,
        )
        for q in result.llm_queries
    ]

    return LLMRecommendationResponse(
        suggestions=base.suggestions,
        profile=base.profile,
        services_used=base.services_used,
        total_candidates_searched=base.total_candidates_searched,
        llm_queries=llm_queries,
        llm_model=get_settings().anthropic_model,
    )


@router.post("/{code}/banner", response_model=EventOut)
@limiter.limit("10/minute")
def upload_banner(
    request: Request,
    file: UploadFile = File(...),
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> EventOut:
    """Upload a custom banner image for the event."""
    from app.services.banner import (
        delete_banner_files,
        process_banner_upload,
        save_banner_to_event,
    )

    # Delete old banner files if replacing
    delete_banner_files(event.banner_filename)

    try:
        banner_filename, _kiosk_filename, colors = process_banner_upload(file, event.code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    save_banner_to_event(db, event, banner_filename, colors)

    return _event_to_out(event, request)


@router.get("/{code}/collection")
def get_collection_settings(
    event: Event = Depends(get_event_for_dj_or_admin),
) -> dict:
    """Get pre-event collection scheduling settings."""
    return collection_settings_payload(event)


@router.patch("/{code}/collection")
def update_collection_settings_endpoint(
    payload: UpdateCollectionSettings,
    event: Event = Depends(get_event_for_dj_or_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Update pre-event collection scheduling settings."""
    update_collection_settings(db, event, payload)
    return collection_settings_payload(event)


@router.post("/{code}/collection/sync-tidal")
@limiter.limit("5/minute")
def sync_collection_to_tidal(
    request: Request,
    background_tasks: BackgroundTasks,
    event: Event = Depends(get_event_for_dj_or_admin),
    db: Session = Depends(get_db),
):
    """Sync all non-rejected collection-phase requests to the DJ's Tidal playlist.

    Includes pending (new) and accepted requests so the DJ can listen to guest
    suggestions on Tidal before the review step.  Already-synced tracks are
    silently skipped inside sync_requests_batch.
    """
    from app.services.system_settings import get_system_settings

    sys_settings = get_system_settings(db)
    if not sys_settings.tidal_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tidal integration is currently unavailable",
        )

    user = event.created_by
    if not user.tidal_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidal account not linked",
        )

    if not event.tidal_sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidal sync not enabled for this event",
        )

    eligible = [
        r for r in event.requests if r.submitted_during_collection and r.status != "rejected"
    ]

    if eligible:
        background_tasks.add_task(sync_collection_requests_batch, db, user, event, eligible)

    return {"queued": len(eligible)}


@router.get("/{code}/pending-review", response_model=PendingReviewResponse)
def pending_review(
    event: Event = Depends(get_event_for_dj_or_admin),
    db: Session = Depends(get_db),
):
    """Get pending review data source for DJ bulk-review."""
    rows = get_pending_review_rows(db, event.id)
    return PendingReviewResponse(
        requests=[
            PendingReviewRow(
                id=r.id,
                song_title=r.song_title,
                artist=r.artist,
                artwork_url=r.artwork_url,
                vote_count=r.vote_count,
                nickname=r.nickname,
                created_at=r.created_at,
                note=r.note,
                status=r.status,
            )
            for r in rows
        ],
        total=len(rows),
    )


@router.post("/{code}/bulk-review", response_model=BulkReviewResponse)
def bulk_review(
    payload: BulkReviewRequest,
    background_tasks: BackgroundTasks,
    event: Event = Depends(get_event_for_dj_or_admin),
    db: Session = Depends(get_db),
):
    accepted, rejected, accepted_rows = execute_bulk_review(db, event.id, payload)
    # Enrich + sync accepted requests. Guest-collect submissions arrive without
    # BPM/key/genre. enrich_request_metadata fills those in directly (Tidal/
    # Beatport/MusicBrainz cascade) — this works regardless of whether the DJ
    # has any sync adapters connected. sync_requests_batch only adds to a
    # connected user's playlists; if no adapters, it returns early as a no-op.
    if accepted_rows:
        for row in accepted_rows:
            background_tasks.add_task(enrich_request_metadata, db, row.id)
        background_tasks.add_task(sync_requests_batch, db, accepted_rows)
    return BulkReviewResponse(accepted=accepted, rejected=rejected, unchanged=0)


ENRICH_ALL_BATCH_LIMIT = 25


def _enrich_with_fresh_session(request_id: int) -> None:
    """Run enrichment in its own DB session.

    The request-scoped `db` from `get_db` stays open until all background tasks finish — for a
    large batch this exhausts the SQLAlchemy connection pool. A fresh `SessionLocal()` per task
    releases its connection as soon as the task ends.
    """
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        enrich_request_metadata(session, request_id)
    finally:
        session.close()


def _sync_requests_with_fresh_session(request_ids: list[int]) -> None:
    """Run sync_requests_batch in its own DB session.

    Same rationale as _enrich_with_fresh_session: the request-scoped `db` stays
    open until all background tasks complete; for large collections this exhausts
    the SQLAlchemy connection pool.  Re-querying by ID inside a fresh session
    releases the connection as soon as the batch finishes.
    """
    from app.db.session import SessionLocal
    from app.models.request import Request as SongRequest

    session = SessionLocal()
    try:
        rows = session.query(SongRequest).filter(SongRequest.id.in_(request_ids)).all()
        if rows:
            sync_requests_batch(session, rows)
    finally:
        session.close()


@router.post("/{code}/enrich-all")
def enrich_all_requests(
    background_tasks: BackgroundTasks,
    event: Event = Depends(get_event_for_dj_or_admin),
    db: Session = Depends(get_db),  # noqa: ARG001 — kept for auth dependency consistency
):
    """Queue enrichment for up to ENRICH_ALL_BATCH_LIMIT requests missing BPM, key, or genre.

    Batched to avoid exhausting the connection pool when many tracks need enrichment.
    Returns `remaining` so the caller can re-invoke until 0.
    """
    candidates = [
        r for r in event.requests if r.bpm is None or r.musical_key is None or r.genre is None
    ]
    batch = candidates[:ENRICH_ALL_BATCH_LIMIT]
    for row in batch:
        background_tasks.add_task(_enrich_with_fresh_session, row.id)
    return {"queued": len(batch), "remaining": max(0, len(candidates) - len(batch))}


@router.delete("/{code}/banner", response_model=EventOut)
@limiter.limit("10/minute")
def delete_banner(
    request: Request,
    event: Event = Depends(get_owned_event),
    db: Session = Depends(get_db),
) -> EventOut:
    """Delete the event's custom banner image."""
    from app.services.banner import delete_banner_from_event

    delete_banner_from_event(db, event)

    return _event_to_out(event, request)
