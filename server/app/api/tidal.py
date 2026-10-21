"""Tidal OAuth and sync API endpoints.

Uses device code OAuth flow for authentication since third-party OAuth
doesn't have access to playlist creation scopes.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db, get_owned_event_by_id, get_owned_request
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.models.event import Event
from app.models.request import Request as SongRequest
from app.models.user import User
from app.schemas.common import StatusMessageResponse, TidalAuthCheckResponse, TidalAuthStartResponse
from app.schemas.tidal import (
    TidalEventSettings,
    TidalEventSettingsUpdate,
    TidalManualLink,
    TidalSearchResult,
    TidalStatus,
    TidalSyncResult,
)
from app.services.providers.tidal import (
    cancel_device_login,
    check_device_login,
    disconnect_tidal,
    manual_link_track,
    search_tidal_tracks,
    start_device_login,
    sync_request_to_tidal,
)
from app.services.system_settings import get_system_settings

router = APIRouter()


@router.post("/auth/start", response_model=TidalAuthStartResponse)
@limiter.limit("10/minute")
def start_auth(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> TidalAuthStartResponse:
    """Start Tidal device login flow.

    Returns a URL and code for the user to visit and authorize.
    The frontend should poll /auth/check to wait for completion.
    """
    sys_settings = get_system_settings(db)
    if not sys_settings.tidal_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tidal integration is currently unavailable",
        )
    result = start_device_login(current_user)
    return TidalAuthStartResponse(
        verification_url=result["verification_url"],
        user_code=result["user_code"],
        message="Visit the URL and enter the code to link your Tidal account",
    )


@router.get("/auth/check", response_model=TidalAuthCheckResponse)
@limiter.limit("30/minute")
def check_auth(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> TidalAuthCheckResponse:
    """Check if device login is complete.

    Returns:
    - complete: true if login succeeded
    - pending: true if still waiting for user
    - error: error message if login failed
    """
    return check_device_login(db, current_user)


@router.post("/auth/cancel", response_model=StatusMessageResponse)
@limiter.limit("30/minute")
def cancel_auth(
    request: Request,
    current_user: User = Depends(get_current_active_user),
) -> StatusMessageResponse:
    """Cancel pending device login."""
    cancel_device_login(current_user)
    return StatusMessageResponse(status="ok", message="Login cancelled")


@router.get("/status", response_model=TidalStatus)
def get_status(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> TidalStatus:
    """Check if current user has linked Tidal account."""
    sys_settings = get_system_settings(db)
    enabled = sys_settings.tidal_enabled

    if not current_user.tidal_access_token:
        return TidalStatus(linked=False, integration_enabled=enabled)

    expires_at = None
    if current_user.tidal_token_expires_at:
        expires_at = current_user.tidal_token_expires_at.isoformat() + "Z"

    return TidalStatus(
        linked=True,
        user_id=current_user.tidal_user_id,
        expires_at=expires_at,
        integration_enabled=enabled,
    )


@router.post("/disconnect", response_model=StatusMessageResponse)
@limiter.limit("10/minute")
def disconnect(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> StatusMessageResponse:
    """Unlink Tidal account from current user."""
    disconnect_tidal(db, current_user)
    return StatusMessageResponse(status="ok", message="Tidal account disconnected")


@router.get("/search", response_model=list[TidalSearchResult])
@limiter.limit(lambda: f"{get_settings().search_rate_limit_per_minute}/minute")
def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> list[TidalSearchResult]:
    """Search Tidal for tracks."""
    sys_settings = get_system_settings(db)
    if not sys_settings.tidal_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tidal integration is currently unavailable",
        )
    if not current_user.tidal_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidal account not linked",
        )
    return search_tidal_tracks(db, current_user, q, limit)


@router.get("/events/{event_id}/settings", response_model=TidalEventSettings)
def get_event_settings(
    event: Event = Depends(get_owned_event_by_id),
    db: Session = Depends(get_db),
) -> TidalEventSettings:
    """Get Tidal sync settings for an event."""
    return TidalEventSettings(
        tidal_sync_enabled=event.tidal_sync_enabled,
        tidal_playlist_id=event.tidal_playlist_id,
    )


@router.put("/events/{event_id}/settings", response_model=TidalEventSettings)
def update_event_settings(
    settings_update: TidalEventSettingsUpdate,
    event: Event = Depends(get_owned_event_by_id),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> TidalEventSettings:
    """Update Tidal sync settings for an event."""
    # Check if user has Tidal linked before enabling sync
    if settings_update.tidal_sync_enabled and not current_user.tidal_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot enable Tidal sync without linked Tidal account",
        )

    event.tidal_sync_enabled = settings_update.tidal_sync_enabled
    db.commit()
    db.refresh(event)

    return TidalEventSettings(
        tidal_sync_enabled=event.tidal_sync_enabled,
        tidal_playlist_id=event.tidal_playlist_id,
    )


@router.post("/requests/{request_id}/sync", response_model=TidalSyncResult)
@limiter.limit("10/minute")
def sync_request(
    request: Request,
    background_tasks: BackgroundTasks,
    song_request: SongRequest = Depends(get_owned_request),
    db: Session = Depends(get_db),
) -> TidalSyncResult:
    """Manually trigger Tidal sync for a request."""
    sys_settings = get_system_settings(db)
    if not sys_settings.tidal_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tidal integration is currently unavailable",
        )
    return sync_request_to_tidal(db, song_request)


@router.post("/requests/{request_id}/link", response_model=TidalSyncResult)
@limiter.limit("10/minute")
def link_track(
    request: Request,
    link_data: TidalManualLink,
    song_request: SongRequest = Depends(get_owned_request),
    db: Session = Depends(get_db),
) -> TidalSyncResult:
    """Manually link a Tidal track to a request."""
    sys_settings = get_system_settings(db)
    if not sys_settings.tidal_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tidal integration is currently unavailable",
        )
    return manual_link_track(db, song_request, link_data.tidal_track_id)
