"""Per-DJ LLM connector management endpoints.

Authentication: ``get_current_active_user`` (any DJ, not pending).
Routes are mounted at ``/api/llm/connectors``.

All endpoints scope queries by ``user_id = current_user.id`` server-side.
404 (not 403) is returned for connector IDs the DJ doesn't own — this avoids
leaking the existence of another DJ's connectors.
"""

from __future__ import annotations

import json as _json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request as FastAPIRequest
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.llm_connector import (
    CONNECTOR_TYPE_OPENAI_COMPATIBLE,
    VALID_CONNECTOR_TYPES,
    LlmConnector,
)
from app.models.user import User
from app.schemas.ai_settings import AIModelsResponse
from app.schemas.llm import (
    KNOWN_FEATURE_VALUES,
    ConnectorCreate,
    ConnectorCredentialsRotate,
    ConnectorOut,
    ConnectorPatch,
    ConnectorTestResult,
    DjPolicyOut,
    FeatureKey,
    FeaturePreferenceOut,
    FeaturePreferenceSet,
    FeaturePreferencesListOut,
)
from app.services.llm.base import ChatRequest as LlmChatRequest
from app.services.llm.base import Message as LlmMessage
from app.services.llm.connector_storage import (
    AUDIT_CREATED,
    AUDIT_CREDENTIALS_ROTATED,
    AUDIT_DEFAULT_SET,
    AUDIT_DEFAULT_UNSET,
    AUDIT_DELETED,
    audit_event,
    build_create_payload,
    clear_feature_preference,
    create_connector,
    delete_connector,
    get_connector_for_user,
    get_feature_preferences_for_user,
    list_connectors_for_user,
    rotate_credentials,
    set_default_for_user,
    set_feature_preference,
    unset_default_for_user,
    update_metadata,
)
from app.services.llm.exceptions import LlmError, NoLlmConfigured
from app.services.llm.gateway import Gateway
from app.services.llm.openrouter_models import get_openrouter_models
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


def _get_owned_connector_or_404(db: Session, connector_id: int, user_id: int) -> LlmConnector:
    """Fetch a connector scoped to its owner, or raise 404.

    Returns 404 (not 403) for IDs the DJ doesn't own so the existence of another
    DJ's connectors is never leaked.
    """
    row = get_connector_for_user(db, connector_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return row


def _audit_and_return(
    db: Session, row: LlmConnector, *, actor_user_id: int, event_type: str
) -> ConnectorOut:
    """Shared write-side epilogue: audit row → commit → refresh → public view.

    The create / rotate / set-default / unset-default endpoints all finish with
    this identical sequence.
    """
    audit_event(db, actor_user_id=actor_user_id, target_connector_id=row.id, event_type=event_type)
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row)


def _feature_prefs_response(db: Session, user_id: int) -> FeaturePreferencesListOut:
    """Build the list response: the DJ's current pins + the pinnable catalogue."""
    rows = get_feature_preferences_for_user(db, user_id)
    return FeaturePreferencesListOut(
        preferences=[FeaturePreferenceOut.model_validate(r) for r in rows],
        known_features=list(KNOWN_FEATURE_VALUES),  # type: ignore[arg-type]
    )


def _raise_if_duplicate_label(exc: Exception) -> None:
    """Translate the per-DJ (display_name, type) unique violation into a 409."""
    if "uq_dj_connector_label" in str(exc):
        raise HTTPException(
            status_code=409,
            detail="You already have a connector with that display name and type",
        ) from exc


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
        _raise_if_duplicate_label(exc)
        logger.exception("Failed to create LLM connector")
        raise HTTPException(status_code=500, detail="Failed to create connector") from exc

    return _audit_and_return(db, row, actor_user_id=user.id, event_type=AUDIT_CREATED)


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
@limiter.limit("30/minute")
def update_connector_metadata(
    request: FastAPIRequest,
    connector_id: int,
    payload: ConnectorPatch,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    row = _get_owned_connector_or_404(db, connector_id, user.id)

    try:
        update_metadata(row, display_name=payload.display_name, model_hint=payload.model_hint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        db.commit()
    except Exception as exc:  # likely a UniqueConstraint collision on rename
        db.rollback()
        _raise_if_duplicate_label(exc)
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
    row = _get_owned_connector_or_404(db, connector_id, user.id)

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

    return _audit_and_return(db, row, actor_user_id=user.id, event_type=AUDIT_CREDENTIALS_ROTATED)


@router.post("/connectors/{connector_id}/test", response_model=ConnectorTestResult)
@limiter.limit("10/minute")
async def test_connector(
    request: FastAPIRequest,
    connector_id: int,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ConnectorTestResult:
    """Run a health check and return a sanitised result.

    Behaviour identical to the background monitor (issue #340), so the
    ``last_health_check_at`` / ``last_health_check_status`` columns and audit
    rows are written the same way on every invocation regardless of trigger
    source. See ``services/llm/health_check.py`` for the shared helper.
    """
    from app.services.llm.health_check import run_health_check

    row = _get_owned_connector_or_404(db, connector_id, user.id)

    outcome = await run_health_check(db, row, actor_user_id=user.id)
    db.commit()

    if outcome.ok:
        return ConnectorTestResult(ok=True)
    # Reuse the same code → message mapping the gateway uses for transient
    # errors. The helper has already sanitised any upstream payload.
    message = {
        "auth_invalid": "Authentication failed against the provider",
        "rate_limited": "Provider rate limited the request",
        "quota_exceeded": "Provider quota or billing failure",
        "provider_unavailable": "Provider unreachable or timed out",
        "error": "Unknown error",
    }.get(outcome.status, "Unknown error")
    return ConnectorTestResult(
        ok=False,
        error_code=outcome.error_code or outcome.status,
        message=message,
    )


# A short, fixed prompt for the streaming health probe. Streams a single
# sentence so the DJ sees tokens arrive in real time, exercising the full
# resolve → adapter.stream → SSE path end-to-end.
_STREAM_TEST_PROMPT = "Reply with one short friendly sentence confirming you are online."


@router.post("/connectors/{connector_id}/stream-test")
@limiter.limit("10/minute")
async def stream_test_connector(
    request: FastAPIRequest,
    connector_id: int,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """Stream a short sentence through the connector as ``text/event-stream``.

    Validates ownership up front (404 for connectors the DJ doesn't own — never
    leaks existence). Each SSE ``data:`` frame is a JSON ``ChatResponseChunk``.
    On a typed gateway error an ``event: error`` frame is emitted carrying only a
    sanitised code (never the upstream payload), then the stream ends. Client
    disconnect cancels the upstream provider request — the gateway generator's
    ``finally`` writes the counts-only call log and closes the adapter.

    Unlike the public guest SSE stream (``api/sse.py``), this endpoint is
    authenticated, rate-limited (10/min), and strictly bounded (max 64 output
    tokens), so it holds the request-scoped DB session for the brief stream
    lifetime rather than opening a detached ``SessionLocal`` — the pool-pinning
    concern that drove ``api/sse.py``'s pattern applies to unauthenticated,
    indefinitely-open guest connections, not a short admin health probe.
    """
    row = _get_owned_connector_or_404(db, connector_id, user.id)

    chat_request = LlmChatRequest(
        messages=[LlmMessage(role="user", content=_STREAM_TEST_PROMPT)],
        max_tokens=64,
        temperature=0.0,
        model=row.model_hint or None,
    )

    async def _publisher():
        try:
            async for chunk in Gateway.stream(db, user, chat_request, purpose="stream_test"):
                yield {"data": _json.dumps(chunk.model_dump())}
        except NoLlmConfigured:
            yield {"event": "error", "data": _json.dumps({"code": "no_connector"})}
        except LlmError as exc:
            # Map to a sanitised, stable code — never echo the provider message.
            code = type(exc).__name__
            logger.info("stream-test failed for connector %s: %s", connector_id, code)
            yield {"event": "error", "data": _json.dumps({"code": code})}

    return EventSourceResponse(
        _publisher(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.post(
    "/connectors/{connector_id}/default",
    response_model=ConnectorOut,
    responses={
        400: {"description": "Connector cannot be set as default (e.g. disabled or auth_invalid)."},
        404: {"description": "Connector not found for current user."},
    },
)
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
    row = _get_owned_connector_or_404(db, connector_id, user.id)
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

    return _audit_and_return(db, row, actor_user_id=user.id, event_type=AUDIT_DEFAULT_SET)


@router.delete(
    "/connectors/{connector_id}/default",
    response_model=ConnectorOut,
    responses={
        404: {"description": "Connector not found for current user."},
    },
)
@limiter.limit("30/minute")
def unset_connector_as_default(
    request: FastAPIRequest,
    connector_id: int,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    """Clear the explicit default — gateway resolution falls back to MRU."""
    row = _get_owned_connector_or_404(db, connector_id, user.id)

    # No-op fast path: don't write an audit row if nothing changed.
    if not row.is_default:
        return ConnectorOut.model_validate(row)

    unset_default_for_user(db, connector=row)
    return _audit_and_return(db, row, actor_user_id=user.id, event_type=AUDIT_DEFAULT_UNSET)


@router.get("/feature-preferences", response_model=FeaturePreferencesListOut)
@limiter.limit("60/minute")
def list_feature_preferences(
    request: FastAPIRequest,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> FeaturePreferencesListOut:
    """List the DJ's per-feature connector pins (issue #337)."""
    return _feature_prefs_response(db, user.id)


@router.post(
    "/feature-preferences",
    response_model=FeaturePreferencesListOut,
    responses={
        400: {"description": "Connector is not active and cannot be pinned."},
        404: {"description": "Connector not found for current user."},
    },
)
@limiter.limit("30/minute")
def set_feature_preference_endpoint(
    request: FastAPIRequest,
    payload: FeaturePreferenceSet,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> FeaturePreferencesListOut:
    """Pin (or re-pin) a connector to a feature for the current DJ.

    Validates connector ownership server-side (404 for IDs the DJ doesn't own,
    so another DJ's connector existence is never leaked) and rejects pinning a
    non-active connector (400) — the gateway would skip it anyway, so silently
    accepting it is a footgun.
    """
    row = _get_owned_connector_or_404(db, payload.connector_id, user.id)
    if row.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Only an active connector can be pinned to a feature",
        )
    set_feature_preference(db, user_id=user.id, feature=payload.feature, connector_id=row.id)
    db.commit()
    return _feature_prefs_response(db, user.id)


@router.delete("/feature-preferences/{feature}", response_model=FeaturePreferencesListOut)
@limiter.limit("30/minute")
def clear_feature_preference_endpoint(
    request: FastAPIRequest,
    feature: FeatureKey,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> FeaturePreferencesListOut:
    """Clear the DJ's pin for ``feature`` (no-op if unset). Returns the new list."""
    clear_feature_preference(db, user_id=user.id, feature=feature)
    db.commit()
    return _feature_prefs_response(db, user.id)


@router.delete("/connectors/{connector_id}", status_code=204)
@limiter.limit("30/minute")
def delete_connector_endpoint(
    request: FastAPIRequest,
    connector_id: int,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> None:
    row = _get_owned_connector_or_404(db, connector_id, user.id)
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
