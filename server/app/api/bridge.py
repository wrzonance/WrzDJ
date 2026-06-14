"""Bridge API endpoints for StageLinQ integration."""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_current_admin, get_db
from app.core.bridge_auth import verify_bridge_api_key
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.models.user import User, UserRole
from app.schemas.bridge_commands import (
    BridgeCommandRequest,
    BridgeCommandResponse,
    BridgeCommandsPollResponse,
)
from app.schemas.common import BridgeApiKeyResponse, StatusResponse
from app.schemas.now_playing import (
    BridgeStatusPayload,
    BridgeStatusResponse,
    NowPlayingBridgePayload,
    NowPlayingResponse,
    PlayHistoryEntry,
    PlayHistoryResponse,
)
from app.services.bridge_integration import poll_commands, queue_command
from app.services.event import (
    EventLookupResult,
    get_event_by_code_for_owner,
    get_event_by_code_with_status,
    get_event_by_join_code_with_status,
)
from app.services.event_bus import publish_event
from app.services.now_playing import (
    clear_now_playing,
    get_now_playing,
    get_play_history,
    handle_now_playing_update,
    update_bridge_status,
)
from app.services.system_settings import get_system_settings

router = APIRouter()


# --- Bridge API Key retrieval (JWT auth, for GUI) ---


@router.get("/bridge/apikey", response_model=BridgeApiKeyResponse)
def get_bridge_api_key(
    _user: User = Depends(get_current_admin),
) -> BridgeApiKeyResponse:
    """
    Return the server's bridge API key to an admin user.

    The GUI uses this so the DJ doesn't have to manually paste the key.
    Restricted to admins to prevent non-owners from impersonating the bridge.
    """
    settings = get_settings()
    if not settings.bridge_api_key:
        raise HTTPException(status_code=503, detail="Bridge API key not configured on server")
    return BridgeApiKeyResponse(bridge_api_key=settings.bridge_api_key)


# --- Bridge Endpoints (API key auth) ---


@router.post("/bridge/nowplaying", response_model=StatusResponse)
@limiter.limit("60/minute")
def post_now_playing(
    request: Request,
    payload: NowPlayingBridgePayload,
    db: Session = Depends(get_db),
    _: None = Depends(verify_bridge_api_key),
) -> StatusResponse:
    """
    Bridge reports a new track playing.

    Called when the DJ loads/plays a new track on their equipment.
    Archives the previous track to play history and updates now_playing.
    Rate limited to 60 requests per minute.
    """
    sys_settings = get_system_settings(db)
    if not sys_settings.bridge_enabled:
        raise HTTPException(status_code=503, detail="Bridge integration is currently unavailable")
    result = handle_now_playing_update(
        db,
        payload.event_code,
        payload.title,
        payload.artist,
        payload.album,
        payload.deck,
        payload.source,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Event not found")
    publish_event(
        payload.event_code,
        "now_playing_changed",
        {
            "title": payload.title,
            "artist": payload.artist,
            "source": payload.source or "bridge",
        },
    )
    return StatusResponse(status="ok")


@router.post("/bridge/status", response_model=StatusResponse)
@limiter.limit("30/minute")
def post_bridge_status(
    request: Request,
    payload: BridgeStatusPayload,
    db: Session = Depends(get_db),
    _: None = Depends(verify_bridge_api_key),
) -> StatusResponse:
    """
    Bridge reports connection status.

    Called when bridge connects/disconnects from DJ equipment.
    Rate limited to 30 requests per minute.
    """
    sys_settings = get_system_settings(db)
    if not sys_settings.bridge_enabled:
        raise HTTPException(status_code=503, detail="Bridge integration is currently unavailable")
    success = update_bridge_status(db, payload.event_code, payload.connected, payload.device_name)
    if not success:
        raise HTTPException(status_code=404, detail="Event not found")
    sse_data: dict = {
        "connected": payload.connected,
        "device_name": payload.device_name,
    }
    # Include enriched fields when present (backward compatible)
    if payload.circuit_breaker_state is not None:
        sse_data["circuit_breaker_state"] = payload.circuit_breaker_state
    if payload.buffer_size is not None:
        sse_data["buffer_size"] = payload.buffer_size
    if payload.plugin_id is not None:
        sse_data["plugin_id"] = payload.plugin_id
    if payload.deck_count is not None:
        sse_data["deck_count"] = payload.deck_count
    if payload.uptime_seconds is not None:
        sse_data["uptime_seconds"] = payload.uptime_seconds
    publish_event(payload.event_code, "bridge_status_changed", sse_data)
    return StatusResponse(status="ok")


@router.delete("/bridge/nowplaying/{code}", response_model=StatusResponse)
@limiter.limit("60/minute")
def delete_now_playing(
    request: Request,
    code: str = Path(..., min_length=1, max_length=10),
    db: Session = Depends(get_db),
    _: None = Depends(verify_bridge_api_key),
) -> StatusResponse:
    """
    Bridge signals track ended / deck cleared.

    Archives current track to history and clears now_playing.
    Rate limited to 60 requests per minute.
    """
    sys_settings = get_system_settings(db)
    if not sys_settings.bridge_enabled:
        raise HTTPException(status_code=503, detail="Bridge integration is currently unavailable")
    success = clear_now_playing(db, code)
    if not success:
        raise HTTPException(status_code=404, detail="Event not found")
    return StatusResponse(status="ok")


# --- Public Endpoints (no auth, for kiosk + guest UI) ---


@router.get("/public/e/{code}/nowplaying", response_model=NowPlayingResponse | None)
@limiter.limit("180/minute")
def get_public_now_playing(
    request: Request,
    code: str,
    db: Session = Depends(get_db),
) -> NowPlayingResponse | None:
    """
    Get current now-playing track for public display.

    Returns the track currently playing from StageLinQ, or None if nothing playing.

    Resolves by join_code: this endpoint serves the kiosk display + OBS overlay
    pages, which route by join_code per the post-PR-#324 public/guest URL contract.
    """
    event, lookup_result = get_event_by_join_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")
    if lookup_result in (EventLookupResult.EXPIRED, EventLookupResult.ARCHIVED):
        raise HTTPException(status_code=410, detail="Event has expired")

    now_playing = get_now_playing(db, event.id)
    if not now_playing or not now_playing.title:
        return None

    return NowPlayingResponse.model_validate(now_playing)


@router.get("/public/e/{code}/bridge-status", response_model=BridgeStatusResponse)
@limiter.limit("180/minute")
def get_public_bridge_status(
    request: Request,
    code: str,
    db: Session = Depends(get_db),
) -> BridgeStatusResponse:
    """
    Get bridge connection status for public display.

    Independent of track data — returns bridge connectivity even when
    no track is currently playing. Resolves by join_code: serves guest-facing
    kiosk display + overlay pages.
    """
    event, lookup_result = get_event_by_join_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")
    if lookup_result in (EventLookupResult.EXPIRED, EventLookupResult.ARCHIVED):
        raise HTTPException(status_code=410, detail="Event has expired")

    now_playing = get_now_playing(db, event.id)
    if not now_playing:
        return BridgeStatusResponse()

    return BridgeStatusResponse(
        connected=now_playing.bridge_connected,
        device_name=now_playing.bridge_device_name,
        last_seen=now_playing.bridge_last_seen,
    )


@router.get("/public/e/{code}/history", response_model=PlayHistoryResponse)
@limiter.limit("180/minute")
def get_public_history(
    request: Request,
    code: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PlayHistoryResponse:
    """
    Get play history for public display.

    Returns the list of tracks played during the event, newest first.
    Resolves by join_code: serves guest-facing kiosk display.
    """
    event, lookup_result = get_event_by_join_code_with_status(db, code)

    if lookup_result == EventLookupResult.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Event not found")
    if lookup_result in (EventLookupResult.EXPIRED, EventLookupResult.ARCHIVED):
        raise HTTPException(status_code=410, detail="Event has expired")

    items, total = get_play_history(db, event.id, limit=limit, offset=offset)
    return PlayHistoryResponse(
        items=[PlayHistoryEntry.model_validate(item) for item in items],
        total=total,
    )


# --- Bridge Command Endpoints ---


@router.post("/bridge/commands/{code}", response_model=BridgeCommandResponse)
@limiter.limit("10/minute")
def post_bridge_command(
    request: Request,
    payload: BridgeCommandRequest,
    code: str = Path(..., min_length=1, max_length=10),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> BridgeCommandResponse:
    """
    Queue a command for the bridge to pick up.

    Requires JWT auth. The user must own the event or be an admin.
    Rate limited to 10 requests per minute.
    """
    # Check ownership or admin role
    event = get_event_by_code_for_owner(db, code, current_user)
    if not event and current_user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=404, detail="Event not found")
    # Admin who doesn't own the event — verify it exists
    if not event:
        found_event, lookup_result = get_event_by_code_with_status(db, code)
        if lookup_result == EventLookupResult.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Event not found")
    command_id = queue_command(code.upper(), payload.command_type)
    return BridgeCommandResponse(
        command_id=command_id,
        command_type=payload.command_type,
    )


@router.get("/bridge/commands/{code}", response_model=BridgeCommandsPollResponse)
@limiter.limit("30/minute")
def get_bridge_commands(
    request: Request,
    code: str = Path(..., min_length=1, max_length=10),
    _: None = Depends(verify_bridge_api_key),
) -> BridgeCommandsPollResponse:
    """
    Poll and clear pending commands for the bridge.

    Requires bridge API key auth. Returns all pending commands and clears the queue.
    Rate limited to 30 requests per minute.
    """
    commands = poll_commands(code.upper())
    return BridgeCommandsPollResponse(
        commands=[
            BridgeCommandResponse(
                command_id=cmd["id"],
                command_type=cmd["type"],
                payload=cmd.get("payload", {}),
            )
            for cmd in commands
        ]
    )
