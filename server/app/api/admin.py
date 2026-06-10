"""Admin API endpoints for user management, event oversight, and system settings."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Request as FastAPIRequest
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db
from app.core.rate_limit import limiter
from app.models.event import Event
from app.models.request import Request
from app.models.user import User, UserRole
from app.schemas.ai_settings import AISettingsOut, AISettingsUpdate
from app.schemas.common import BulkActionResponse
from app.schemas.event import BulkDeleteEventsRequest, EventUpdate
from app.schemas.integration_health import (
    IntegrationCheckResponse,
    IntegrationHealthResponse,
    IntegrationToggleRequest,
    IntegrationToggleResponse,
)
from app.schemas.system_settings import SystemSettingsOut, SystemSettingsUpdate
from app.schemas.user import (
    AdminEventOut,
    AdminUserCreate,
    AdminUserOut,
    AdminUserUpdate,
    PaginatedResponse,
    SystemStats,
)
from app.services.admin import (
    count_admins,
    create_user_admin,
    delete_user,
    get_all_events_admin,
    get_all_users,
    get_system_stats,
    get_user_by_id,
    update_user_admin,
)
from app.services.auth import get_user_by_username
from app.services.event import bulk_delete_events, delete_event, update_event
from app.services.integration_health import (
    VALID_SERVICES,
    check_integration_health,
    get_all_integration_statuses,
)
from app.services.system_settings import get_system_settings, update_system_settings

router = APIRouter()


@router.get("/stats", response_model=SystemStats)
@limiter.limit("120/minute")
def admin_stats(
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> SystemStats:
    stats = get_system_stats(db)
    return SystemStats(**stats)


@router.get("/users", response_model=PaginatedResponse)
@limiter.limit("120/minute")
def admin_list_users(
    request: FastAPIRequest,
    page: int = Query(default=1, ge=1, le=1000),
    limit: int = Query(default=20, ge=1, le=100),
    role: str | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> PaginatedResponse:
    if role and role not in [r.value for r in UserRole]:
        raise HTTPException(status_code=400, detail="Invalid role filter")
    items, total = get_all_users(db, page=page, limit=limit, role_filter=role)
    return PaginatedResponse(items=items, total=total, page=page, limit=limit)


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def admin_create_user(
    user_data: AdminUserCreate,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> AdminUserOut:
    if user_data.role not in [r.value for r in UserRole]:
        raise HTTPException(status_code=400, detail="Invalid role")
    existing = get_user_by_username(db, user_data.username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = create_user_admin(db, user_data.username, user_data.password, user_data.role)
    return AdminUserOut(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        role=user.role,
        created_at=user.created_at,
        event_count=0,
    )


@router.patch("/users/{user_id}", response_model=AdminUserOut)
@limiter.limit("30/minute")
def admin_update_user(
    user_id: int,
    update_data: AdminUserUpdate,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> AdminUserOut:
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate role if provided
    if update_data.role is not None and update_data.role not in [r.value for r in UserRole]:
        raise HTTPException(status_code=400, detail="Invalid role")

    # Last-admin protection: prevent demoting/deactivating the last admin
    if user.role == UserRole.ADMIN.value:
        is_demoting = update_data.role is not None and update_data.role != UserRole.ADMIN.value
        is_deactivating = update_data.is_active is False
        if (is_demoting or is_deactivating) and count_admins(db) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last admin")

    updated = update_user_admin(
        db,
        user,
        role=update_data.role,
        is_active=update_data.is_active,
        password=update_data.password,
    )
    event_count = (
        db.query(func.count(Event.id)).filter(Event.created_by_user_id == updated.id).scalar()
    )
    return AdminUserOut(
        id=updated.id,
        username=updated.username,
        is_active=updated.is_active,
        role=updated.role,
        created_at=updated.created_at,
        event_count=event_count or 0,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def admin_delete_user(
    user_id: int,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> None:
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if user.role == UserRole.ADMIN.value and count_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last admin")
    delete_user(db, user)


@router.get("/events", response_model=PaginatedResponse)
@limiter.limit("120/minute")
def admin_list_events(
    request: FastAPIRequest,
    page: int = Query(default=1, ge=1, le=1000),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> PaginatedResponse:
    items, total = get_all_events_admin(db, page=page, limit=limit)
    return PaginatedResponse(items=items, total=total, page=page, limit=limit)


@router.patch("/events/{code}", response_model=AdminEventOut)
@limiter.limit("30/minute")
def admin_update_event(
    code: str,
    event_data: EventUpdate,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> AdminEventOut:
    """Admin can edit any event (not just their own)."""
    event = db.query(Event).filter(Event.code == code.upper()).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    updated = update_event(
        db,
        event,
        name=event_data.name,
        expires_at=event_data.expires_at,
    )
    owner = db.query(User).filter(User.id == updated.created_by_user_id).first()
    req_count = db.query(func.count(Request.id)).filter(Request.event_id == updated.id).scalar()
    return AdminEventOut(
        id=updated.id,
        code=updated.code,
        join_code=updated.join_code,
        name=updated.name,
        owner_username=owner.username if owner else "unknown",
        owner_id=updated.created_by_user_id,
        created_at=updated.created_at,
        expires_at=updated.expires_at,
        is_active=updated.is_active,
        request_count=req_count or 0,
    )


@router.delete("/events/{code}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def admin_delete_event(
    code: str,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> None:
    """Admin can delete any event."""
    event = db.query(Event).filter(Event.code == code.upper()).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    delete_event(db, event)


@router.post("/events/bulk-delete", response_model=BulkActionResponse)
@limiter.limit("5/minute")
def admin_bulk_delete_events(
    request: FastAPIRequest,
    body: BulkDeleteEventsRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> BulkActionResponse:
    """Admin can bulk delete events from any owner."""
    try:
        count = bulk_delete_events(db, body.codes, user=None)
    except ValueError:
        raise HTTPException(status_code=404, detail="One or more events not found")
    return BulkActionResponse(status="ok", count=count)


@router.get("/settings", response_model=SystemSettingsOut)
@limiter.limit("120/minute")
def admin_get_settings(
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> SystemSettingsOut:
    settings = get_system_settings(db)
    return SystemSettingsOut.model_validate(settings)


@router.patch("/settings", response_model=SystemSettingsOut)
@limiter.limit("30/minute")
def admin_update_settings(
    update_data: SystemSettingsUpdate,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> SystemSettingsOut:
    settings = update_system_settings(
        db,
        registration_enabled=update_data.registration_enabled,
        search_rate_limit_per_minute=update_data.search_rate_limit_per_minute,
        spotify_enabled=update_data.spotify_enabled,
        tidal_enabled=update_data.tidal_enabled,
        beatport_enabled=update_data.beatport_enabled,
        bridge_enabled=update_data.bridge_enabled,
        human_verification_enforced=update_data.human_verification_enforced,
        llm_enabled=update_data.llm_enabled,
        llm_rate_limit_per_minute=update_data.llm_rate_limit_per_minute,
    )
    return SystemSettingsOut.model_validate(settings)


@router.get("/integrations", response_model=IntegrationHealthResponse)
@limiter.limit("60/minute")
def admin_get_integrations(
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> IntegrationHealthResponse:
    """Get status of all external integrations (no active health checks)."""
    services = get_all_integration_statuses(db)
    return IntegrationHealthResponse(services=services)


@router.patch("/integrations/{service}", response_model=IntegrationToggleResponse)
@limiter.limit("30/minute")
def admin_toggle_integration(
    service: str,
    toggle: IntegrationToggleRequest,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> IntegrationToggleResponse:
    """Enable or disable a specific integration."""
    if service not in VALID_SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")

    update_system_settings(db, **{f"{service}_enabled": toggle.enabled})
    return IntegrationToggleResponse(service=service, enabled=toggle.enabled)


@router.post("/integrations/{service}/check", response_model=IntegrationCheckResponse)
@limiter.limit("10/minute")
def admin_check_integration(
    request: FastAPIRequest,
    service: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> IntegrationCheckResponse:
    """Run an active health check for a specific service (rate limited)."""
    if service not in VALID_SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")

    healthy, capabilities, error = check_integration_health(db, service)
    return IntegrationCheckResponse(
        service=service,
        healthy=healthy,
        capabilities=capabilities,
        error=error,
    )


# ========== AI / LLM Settings ==========


@router.get("/ai/settings", response_model=AISettingsOut)
@limiter.limit("120/minute")
def admin_get_ai_settings(
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> AISettingsOut:
    """Get AI/LLM configuration.

    ``llm_enabled`` gates only the org-connector fallback — DJs with their own
    connector are never blocked by it. Credential status lives on the connector
    surfaces (``/api/admin/llm/*``).
    """
    settings = get_system_settings(db)
    return AISettingsOut(
        llm_enabled=settings.llm_enabled,
        llm_rate_limit_per_minute=settings.llm_rate_limit_per_minute,
    )


@router.put("/ai/settings", response_model=AISettingsOut)
@limiter.limit("30/minute")
def admin_update_ai_settings(
    update_data: AISettingsUpdate,
    request: FastAPIRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
) -> AISettingsOut:
    """Update AI/LLM configuration (org-fallback gate + public rate limit)."""
    settings = update_system_settings(
        db,
        llm_enabled=update_data.llm_enabled,
        llm_rate_limit_per_minute=update_data.llm_rate_limit_per_minute,
    )
    return AISettingsOut(
        llm_enabled=settings.llm_enabled,
        llm_rate_limit_per_minute=settings.llm_rate_limit_per_minute,
    )
