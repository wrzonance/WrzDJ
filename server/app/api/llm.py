"""Per-DJ LLM connector management endpoints.

Authentication: ``get_current_active_user`` (any DJ, not pending).
Routes are mounted at ``/api/llm/connectors``.

All endpoints scope queries by ``user_id = current_user.id`` server-side.
404 (not 403) is returned for connector IDs the DJ doesn't own — this avoids
leaking the existence of another DJ's connectors.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request as FastAPIRequest
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.llm_connector import (
    CONNECTOR_TYPE_OPENAI_COMPATIBLE,
    STATUS_DISABLED,
    VALID_CONNECTOR_TYPES,
)
from app.models.user import User
from app.schemas.ai_settings import AIModelsResponse
from app.schemas.llm import (
    ConnectorCreate,
    ConnectorCredentialsRotate,
    ConnectorOut,
    ConnectorPatch,
    ConnectorTestResult,
    DjPolicyOut,
)
from app.services.llm.connector_storage import (
    AUDIT_CREATED,
    AUDIT_CREDENTIALS_ROTATED,
    AUDIT_DEFAULT_SET,
    AUDIT_DEFAULT_UNSET,
    AUDIT_DELETED,
    AUDIT_HEALTH_CHECK,
    audit_event,
    build_create_payload,
    create_connector,
    delete_connector,
    get_connector_for_user,
    list_connectors_for_user,
    rotate_credentials,
    set_default_for_user,
    unset_default_for_user,
    update_metadata,
)
from app.services.llm.exceptions import (
    AuthInvalid,
    LlmError,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
from app.services.llm.openrouter_models import get_openrouter_models
from app.services.llm.registry import get_adapter_class
from app.services.system_settings import get_system_settings

logger = logging.getLogger(__name__)

router = APIRouter()


# API-key connector types (everything that isn't the custom OpenAI-compatible
# endpoint). Gated by the single ``llm_apikey_connectors_enabled`` flag, mirroring
# ``_check_connector_type_allowed`` below. Sorted for a deterministic response.
_APIKEY_CONNECTOR_TYPES: tuple[str, ...] = tuple(
    sorted(VALID_CONNECTOR_TYPES - {CONNECTOR_TYPE_OPENAI_COMPATIBLE})
)


def _allowed_connector_types(*, apikey_enabled: bool, compatible_enabled: bool) -> list[str]:
    """Compute the connector types a DJ may create under the given policy.

    Kept consistent with ``_check_connector_type_allowed`` so the advertised set
    exactly matches what the create endpoint will accept (no UX/enforcement drift).
    """
    allowed: list[str] = []
    if apikey_enabled:
        allowed.extend(_APIKEY_CONNECTOR_TYPES)
    if compatible_enabled:
        allowed.append(CONNECTOR_TYPE_OPENAI_COMPATIBLE)
    return allowed


def _check_connector_type_allowed(db: Session, connector_type: str) -> None:
    """Enforce the admin policy toggles. Raises 403 when blocked."""
    settings = get_system_settings(db)
    if connector_type == CONNECTOR_TYPE_OPENAI_COMPATIBLE:
        if not settings.llm_compatible_connector_enabled:
            raise HTTPException(
                status_code=403,
                detail="Custom OpenAI-compatible connectors are disabled by admin policy",
            )
    elif connector_type in VALID_CONNECTOR_TYPES:
        if not settings.llm_apikey_connectors_enabled:
            raise HTTPException(
                status_code=403,
                detail="API-key connectors are disabled by admin policy",
            )


def _sanitize_error(exc: Exception) -> tuple[str, str]:
    """Map an LLM exception to (error_code, user-friendly message).

    Upstream error bodies / stack traces are deliberately NOT included.
    """
    if isinstance(exc, AuthInvalid):
        return "auth_invalid", "Authentication failed against the provider"
    if isinstance(exc, RateLimited):
        return "rate_limited", "Provider rate limited the request"
    if isinstance(exc, QuotaExceeded):
        return "quota_exceeded", "Provider quota or billing failure"
    if isinstance(exc, ProviderUnavailable):
        return "provider_unavailable", "Provider unreachable or timed out"
    if isinstance(exc, ToolTranslationError):
        return "tool_translation_error", "Unexpected response shape"
    if isinstance(exc, LlmError):
        return "llm_error", "LLM error"
    return "unknown", "Unknown error"


@router.get("/connectors", response_model=list[ConnectorOut])
@limiter.limit("60/minute")
def list_connectors(
    request: FastAPIRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> list[ConnectorOut]:
    rows = list_connectors_for_user(db, user.id)
    return [ConnectorOut.model_validate(r) for r in rows]


@router.get(
    "/policy",
    response_model=DjPolicyOut,
    responses={
        401: {"description": "Not authenticated (missing or invalid bearer token)."},
        403: {"description": "Authenticated but not an active DJ (e.g. pending approval)."},
    },
)
@limiter.limit("60/minute")
def get_dj_policy(
    request: FastAPIRequest,
    _user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> DjPolicyOut:
    """DJ-readable connector policy (non-sensitive subset).

    The settings/ai page consumes this to fail *closed* — hiding connector
    types the admin has disabled rather than showing every provider and only
    discovering the block when the create call returns 403. Admin-only fields
    (e.g. ``llm_default_connector_id``) are intentionally excluded.
    """
    settings = get_system_settings(db)
    return DjPolicyOut(
        llm_apikey_connectors_enabled=settings.llm_apikey_connectors_enabled,
        llm_compatible_connector_enabled=settings.llm_compatible_connector_enabled,
        allowed_connector_types=_allowed_connector_types(
            apikey_enabled=settings.llm_apikey_connectors_enabled,
            compatible_enabled=settings.llm_compatible_connector_enabled,
        ),  # type: ignore[arg-type]
    )


@router.get("/openrouter/models", response_model=AIModelsResponse)
@limiter.limit("30/minute")
async def list_openrouter_models(
    request: FastAPIRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> AIModelsResponse:
    """Return the OpenRouter model catalogue for the model-hint dropdown.

    Served from a process-wide TTL cache (refreshed hourly). The OpenRouter
    ``/models`` endpoint is public, so no connector credentials are required.
    Returns an empty list if the catalogue is unavailable — the frontend then
    falls back to a free-text model input.
    """
    models = await get_openrouter_models()
    return AIModelsResponse(models=models)


@router.post("/connectors", response_model=ConnectorOut, status_code=201)
@limiter.limit("5/minute")
def create_connector_endpoint(
    request: FastAPIRequest,
    payload: ConnectorCreate,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    _check_connector_type_allowed(db, payload.connector_type)

    try:
        built = build_create_payload(
            connector_type=payload.connector_type,
            display_name=payload.display_name,
            api_key=payload.api_key,
            base_url=payload.base_url,
            bearer=payload.bearer,
            model_hint=payload.model_hint,
            aws_access_key_id=payload.aws_access_key_id,
            aws_secret_access_key=payload.aws_secret_access_key,
            aws_region=payload.aws_region,
            aws_model_id=payload.aws_model_id,
            azure_resource_name=payload.azure_resource_name,
            azure_deployment_name=payload.azure_deployment_name,
            azure_api_version=payload.azure_api_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        row = create_connector(db, user_id=user.id, payload=built)
    except Exception as exc:  # likely a UniqueConstraint collision
        db.rollback()
        if "uq_dj_connector_label" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="You already have a connector with that display name and type",
            ) from exc
        logger.exception("Failed to create LLM connector")
        raise HTTPException(status_code=500, detail="Failed to create connector") from exc

    audit_event(
        db,
        actor_user_id=user.id,
        target_connector_id=row.id,
        event_type=AUDIT_CREATED,
    )
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row)


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
@limiter.limit("30/minute")
def update_connector_metadata(
    request: FastAPIRequest,
    connector_id: int,
    payload: ConnectorPatch,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    row = get_connector_for_user(db, connector_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    try:
        update_metadata(row, display_name=payload.display_name, model_hint=payload.model_hint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        db.commit()
    except Exception as exc:  # likely a UniqueConstraint collision on rename
        db.rollback()
        if "uq_dj_connector_label" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="You already have a connector with that display name and type",
            ) from exc
        logger.exception("Failed to update LLM connector metadata")
        raise HTTPException(status_code=500, detail="Failed to update connector metadata") from exc
    db.refresh(row)
    return ConnectorOut.model_validate(row)


@router.put("/connectors/{connector_id}/credentials", response_model=ConnectorOut)
@limiter.limit("5/minute")
def rotate_connector_credentials(
    request: FastAPIRequest,
    connector_id: int,
    payload: ConnectorCredentialsRotate,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    row = get_connector_for_user(db, connector_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    try:
        rotate_credentials(
            db,
            connector=row,
            api_key=payload.api_key,
            base_url=payload.base_url,
            bearer=payload.bearer,
            aws_access_key_id=payload.aws_access_key_id,
            aws_secret_access_key=payload.aws_secret_access_key,
            aws_region=payload.aws_region,
            aws_model_id=payload.aws_model_id,
            azure_resource_name=payload.azure_resource_name,
            azure_deployment_name=payload.azure_deployment_name,
            azure_api_version=payload.azure_api_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        actor_user_id=user.id,
        target_connector_id=row.id,
        event_type=AUDIT_CREDENTIALS_ROTATED,
    )
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row)


@router.post("/connectors/{connector_id}/test", response_model=ConnectorTestResult)
@limiter.limit("10/minute")
async def test_connector(
    request: FastAPIRequest,
    connector_id: int,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ConnectorTestResult:
    row = get_connector_for_user(db, connector_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    adapter_cls = get_adapter_class(row.connector_type)
    adapter = adapter_cls(row)

    audit_event(
        db,
        actor_user_id=user.id,
        target_connector_id=row.id,
        event_type=AUDIT_HEALTH_CHECK,
    )

    try:
        await adapter.health_check()
    except AuthInvalid as exc:
        row.status = "auth_invalid"
        row.last_error = "auth_invalid"
        db.commit()
        code, message = _sanitize_error(exc)
        return ConnectorTestResult(ok=False, error_code=code, message=message)
    except LlmError as exc:
        # Don't flip status for transient errors — DJ will see message + retry.
        code, message = _sanitize_error(exc)
        db.commit()
        return ConnectorTestResult(ok=False, error_code=code, message=message)
    except Exception:  # noqa: BLE001 — sanitised
        logger.exception("Connector health check failed unexpectedly")
        db.commit()
        return ConnectorTestResult(ok=False, error_code="unknown", message="Unknown error")

    row.last_error = None
    if row.status != STATUS_DISABLED:
        row.status = "active"
    db.commit()
    return ConnectorTestResult(ok=True)


@router.post("/connectors/{connector_id}/default", response_model=ConnectorOut)
@limiter.limit("30/minute")
def set_connector_as_default(
    request: FastAPIRequest,
    connector_id: int,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    """Pin this connector as the DJ's explicit default (issue #336).

    Atomically clears any other defaults the DJ owns before flipping this row,
    so the partial unique index never sees two True rows for the same user.

    Setting a disabled / auth_invalid connector as default is rejected with 400
    so DJs don't silently break their own routing — a default that the gateway
    would skip anyway is a footgun.
    """
    row = get_connector_for_user(db, connector_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    if row.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Only an active connector can be set as default",
        )

    try:
        set_default_for_user(db, connector=row)
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to set LLM connector as default")
        raise HTTPException(status_code=500, detail="Failed to set default") from exc

    audit_event(
        db,
        actor_user_id=user.id,
        target_connector_id=row.id,
        event_type=AUDIT_DEFAULT_SET,
    )
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row)


@router.delete("/connectors/{connector_id}/default", response_model=ConnectorOut)
@limiter.limit("30/minute")
def unset_connector_as_default(
    request: FastAPIRequest,
    connector_id: int,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    """Clear the explicit default — gateway resolution falls back to MRU."""
    row = get_connector_for_user(db, connector_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    # No-op fast path: don't write an audit row if nothing changed.
    if not row.is_default:
        return ConnectorOut.model_validate(row)

    unset_default_for_user(db, connector=row)
    audit_event(
        db,
        actor_user_id=user.id,
        target_connector_id=row.id,
        event_type=AUDIT_DEFAULT_UNSET,
    )
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row)


@router.delete("/connectors/{connector_id}", status_code=204)
@limiter.limit("30/minute")
def delete_connector_endpoint(
    request: FastAPIRequest,
    connector_id: int,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> None:
    row = get_connector_for_user(db, connector_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    audit_event(
        db,
        actor_user_id=user.id,
        target_connector_id=row.id,
        event_type=AUDIT_DELETED,
    )
    # If this connector is the system default, clear it before deletion to
    # mirror the admin revoke path (and to be correct on SQLite, where the FK
    # ON DELETE SET NULL may not fire).
    settings = get_system_settings(db)
    if settings.llm_default_connector_id == row.id:
        settings.llm_default_connector_id = None
    delete_connector(db, row)
    db.commit()
    return None
