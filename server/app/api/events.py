import json
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_current_user_optional,
    get_db,
    get_owned_event,
    require_verified_human_soft,
)
from app.api.event_status import raise_for_unavailable_event
from app.api.events_collection import router as collection_router
from app.api.events_recommendations import router as recommendations_router
from app.api.events_requests import router as requests_router
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.models.event import Event
from app.models.user import User, UserRole
from app.schemas.activity_log import ActivityLogEntry
from app.schemas.common import BulkActionResponse
from app.schemas.event import (
    BulkDeleteEventsRequest,
    DisplaySettingsResponse,
    DisplaySettingsUpdate,
    EventCreate,
    EventOut,
    EventUpdate,
)
from app.schemas.search import SearchResult
from app.services.activity_log import get_recent_activity
from app.services.event import (
    EventLookupResult,
    archive_event,
    bulk_delete_events,
    compute_event_status,
    create_event,
    delete_event,
    get_archived_events_for_user,
    get_event_by_code_with_status,
    get_event_by_public_code_with_status,
    get_events_for_user,
    get_expired_events_for_user,
    unarchive_event,
    update_event,
)
from app.services.intent_parser import parse_intent
from app.services.kiosk import is_trusted_kiosk_for_event
from app.services.now_playing import (
    get_manual_hide_setting,
    set_now_playing_visibility,
)

from . import events_exports

router = APIRouter()
router.include_router(requests_router)
router.include_router(collection_router)

# Preserve the previous module-level exports for callers that imported these names.
MAX_EXPORT_PLAY_HISTORY = events_exports.MAX_EXPORT_PLAY_HISTORY
MAX_EXPORT_REQUESTS = events_exports.MAX_EXPORT_REQUESTS
export_event_csv = events_exports.export_event_csv
export_play_history_csv = events_exports.export_play_history_csv


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize an incoming datetime to naive UTC (matches the project's stored convention).

    Frontend sends ISO strings with timezone (`Z` suffix), which Pydantic parses as
    aware datetimes. The DB columns are naive; comparing aware to naive raises
    TypeError. Strip tz to UTC-naive for storage.
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def _get_base_url(request: Request | None) -> str | None:
    """Get the base URL for constructing public URLs."""
    settings = get_settings()
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


def _event_to_out(
    event,
    request: Request | None = None,
    request_count: int | None = None,
    include_status: bool = False,
) -> EventOut:
    """Convert Event model to EventOut schema with join_url and collect_url."""
    base_url = _get_base_url(request)
    join_url = f"{base_url}/join/{event.join_code}" if base_url else None
    collect_url = f"{base_url}/collect/{event.code}" if base_url else None

    event_status = compute_event_status(event) if include_status else None

    banner_url, banner_kiosk_url = _get_banner_urls(event, request)
    try:
        banner_colors = json.loads(event.banner_colors) if event.banner_colors else None
    except (json.JSONDecodeError, TypeError):
        banner_colors = None

    return EventOut(
        id=event.id,
        code=event.code,
        join_code=event.join_code,
        name=event.name,
        created_at=event.created_at,
        expires_at=event.expires_at,
        is_active=event.is_active,
        archived_at=event.archived_at,
        status=event_status,
        join_url=join_url,
        collect_url=collect_url,
        request_count=request_count,
        tidal_sync_enabled=event.tidal_sync_enabled,
        tidal_playlist_id=event.tidal_playlist_id,
        beatport_sync_enabled=event.beatport_sync_enabled,
        beatport_playlist_id=event.beatport_playlist_id,
        banner_url=banner_url,
        banner_kiosk_url=banner_kiosk_url,
        banner_colors=banner_colors,
        requests_open=event.requests_open,
        frictionless_join=event.frictionless_join,
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
) -> list[ActivityLogEntry]:
    """Get recent activity log entries for the current user's events."""
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
def get_event(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EventOut:
    event, lookup_result = get_event_by_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")

    # EventOut exposes event.id + both codes + share URLs, so this endpoint is
    # restricted to the owning DJ or an admin. Non-owners get 404 (not 403) to
    # avoid leaking event existence. (Was public before #382 hardening.)
    is_owner = event.created_by_user_id == current_user.id
    is_admin = current_user.role == UserRole.ADMIN.value
    if not (is_owner or is_admin):
        raise HTTPException(status_code=404, detail="Event not found")

    raise_for_unavailable_event(lookup_result)

    return _event_to_out(event, request)


@router.get("/{code}/search", response_model=list[SearchResult])
@limiter.limit(lambda: f"{get_settings().search_rate_limit_per_minute}/minute")
def event_search(
    code: str,
    request: Request,
    response: Response,
    q: str = Query(..., min_length=2, max_length=200),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[SearchResult]:
    """Public search endpoint for event guests.

    Priority: Tidal (primary) → Spotify (fallback) → Beatport (event toggle).
    Results are filtered for junk, deduplicated by ISRC, and sorted by popularity.

    Auth model: anonymous guests must pass the human-verification gate
    (require_verified_human_soft). The authenticated event OWNER bypasses it —
    the DJ dashboard "Search for Song" tool reuses this endpoint, and the DJ
    holds a JWT but no guest wrzdj_human cookie, so without the bypass an
    enforced gate would 403 them on their own event.
    """
    from app.services.providers.beatport import search_beatport_tracks
    from app.services.providers.spotify import search_songs
    from app.services.providers.tidal import search_tidal_tracks
    from app.services.search_merge import build_search_results
    from app.services.system_settings import get_system_settings

    event_obj, lookup_result = get_event_by_public_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")

    if lookup_result in (EventLookupResult.EXPIRED, EventLookupResult.ARCHIVED):
        raise HTTPException(status_code=410, detail="Event has expired")

    # The authenticated owner AND a paired kiosk (a trusted physical device on
    # this event) both bypass the guest human-verification gate. The kiosk holds
    # no JWT and no wrzdj_human cookie, so without this an enforced gate 403s
    # every kiosk search (issue #514). Everyone else passes through the gate.
    is_owner = current_user is not None and current_user.id == event_obj.created_by_user_id
    is_kiosk = is_trusted_kiosk_for_event(db, request.headers.get("X-Kiosk-Session"), event_obj)
    if not is_owner and not is_kiosk:
        require_verified_human_soft(request, response, db)

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

    # Beatport is available only when global, owner, and event gates all pass.
    beatport_search_available = bool(
        sys_settings.beatport_enabled
        and owner
        and owner.beatport_access_token
        and event_obj.beatport_sync_enabled
    )
    beatport_results = []
    if beatport_search_available:
        beatport_results = search_beatport_tracks(db, owner, q, limit=10)

    has_any_source = (
        (owner and owner.tidal_access_token)
        or sys_settings.spotify_enabled
        or beatport_search_available
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
        frictionless_join=event_data.frictionless_join,
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


router.include_router(events_exports.router)
router.include_router(recommendations_router)
