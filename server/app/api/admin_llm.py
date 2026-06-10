"""Admin LLM policy + connector oversight endpoints.

Authentication: ``get_current_admin``.
Routes are mounted at ``/api/admin/llm``.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterator
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db
from app.core.csv_safe import sanitize_csv_value
from app.core.rate_limit import limiter
from app.core.time import utcnow
from app.models.llm_connector import LlmAuditEvent, LlmConnector
from app.models.user import User
from app.schemas.llm import (
    AdminAuditOut,
    AdminConnectorCapPatch,
    AdminConnectorOut,
    AdminPolicyOut,
    AdminPolicyPatch,
    AdminUsageOut,
    AuditEventRow,
    ConnectorCreate,
    ConnectorCredentialsRotate,
    ConnectorOut,
    ConnectorTestResult,
    UsageRow,
)
from app.services.llm.connector_storage import (
    AUDIT_CREATED,
    AUDIT_CREDENTIALS_ROTATED,
    AUDIT_DELETED,
    AUDIT_POLICY_CHANGED,
    AUDIT_REVOKED_BY_ADMIN,
    audit_event,
    build_create_payload,
    create_connector,
    current_month_token_usage,
    current_month_token_usage_bulk,
    delete_connector,
    get_connector,
    get_usage_stats,
    get_user_label,
    list_all_connectors,
    list_org_connectors,
    owner_label,
    revoke_connector,
    rotate_credentials,
    set_monthly_cap,
)
from app.services.system_settings import get_system_settings, update_system_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Hard ceiling for a single CSV export — keeps an attacker (or an honest admin
# with a huge history) from streaming an unbounded result set.
_AUDIT_CSV_ROW_CAP = 10_000


def _connector_to_admin_out(
    row: LlmConnector, dj_username: str, current_month_tokens: int = 0
) -> AdminConnectorOut:
    """Reflect a connector row + its owner's display name into the admin view.

    ``AdminConnectorOut`` adds ``dj_username`` and ``current_month_tokens``,
    which aren't columns on the row, so the model is validated from a
    column-reflection dict plus those extras rather than the ORM object
    directly.
    """
    return AdminConnectorOut.model_validate(
        {
            **{c.name: getattr(row, c.name) for c in LlmConnector.__table__.columns},
            "dj_username": dj_username,
            "current_month_tokens": current_month_tokens,
        }
    )


def _actor_label(event: LlmAuditEvent, actor_username: str | None) -> str:
    """Display label for an audit row's actor.

    NULL-actor rows (gateway system calls, org-row health checks) render as
    "system"; a non-NULL actor whose user row has been deleted falls back to
    "user#<id>". Shared by the JSON browse endpoint and the CSV export so the
    two surfaces can never drift.
    """
    if actor_username:
        return actor_username
    return "system" if event.actor_user_id is None else f"user#{event.actor_user_id}"


def _get_org_connector_or_404(db: Session, connector_id: int) -> LlmConnector:
    """Fetch an org-scoped connector or raise 404.

    User-scoped rows return 404 (not 403) from the org endpoints so a DJ's
    personal connector IDs are never confirmed through the admin org surface.
    """
    row = get_connector(db, connector_id)
    if row is None or row.scope != "org":
        raise HTTPException(status_code=404, detail="Connector not found")
    return row


def _audit_query(
    db: Session,
    *,
    event_type: str | None,
    actor_user_id: int | None,
    target_connector_id: int | None,
    days: int,
):
    """Build the base SELECT joining actor username + connector display name.

    Read-only: never touches the encrypted ``credentials`` column. Returns a
    Core ``Select`` over (LlmAuditEvent, actor_username, connector_display_name)
    so both the JSON browse endpoint and the CSV export share one filter path.
    """
    cutoff = utcnow() - timedelta(days=days)
    stmt = (
        select(
            LlmAuditEvent,
            User.username.label("actor_username"),
            LlmConnector.display_name.label("connector_display_name"),
        )
        .join(User, User.id == LlmAuditEvent.actor_user_id, isouter=True)
        .join(
            LlmConnector,
            LlmConnector.id == LlmAuditEvent.target_connector_id,
            isouter=True,
        )
        .where(LlmAuditEvent.created_at >= cutoff)
    )
    if event_type is not None:
        stmt = stmt.where(LlmAuditEvent.event_type == event_type)
    if actor_user_id is not None:
        stmt = stmt.where(LlmAuditEvent.actor_user_id == actor_user_id)
    if target_connector_id is not None:
        stmt = stmt.where(LlmAuditEvent.target_connector_id == target_connector_id)
    return stmt


@router.get("/policy", response_model=AdminPolicyOut)
@limiter.limit("60/minute")
def get_policy(
    request: FastAPIRequest,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminPolicyOut:
    settings = get_system_settings(db)
    return AdminPolicyOut(
        llm_apikey_connectors_enabled=settings.llm_apikey_connectors_enabled,
        llm_compatible_connector_enabled=settings.llm_compatible_connector_enabled,
        llm_default_connector_id=settings.llm_default_connector_id,
        llm_call_log_retention_days=settings.llm_call_log_retention_days,
    )


@router.patch("/policy", response_model=AdminPolicyOut)
@limiter.limit("30/minute")
def patch_policy(
    request: FastAPIRequest,
    payload: AdminPolicyPatch,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminPolicyOut:
    update_kwargs: dict = {}
    if payload.llm_apikey_connectors_enabled is not None:
        update_kwargs["llm_apikey_connectors_enabled"] = payload.llm_apikey_connectors_enabled
    if payload.llm_compatible_connector_enabled is not None:
        update_kwargs["llm_compatible_connector_enabled"] = payload.llm_compatible_connector_enabled
    if payload.llm_call_log_retention_days is not None:
        update_kwargs["llm_call_log_retention_days"] = payload.llm_call_log_retention_days

    # Default connector handling:
    # - clear_default=True takes precedence and sets to NULL
    # - explicit `llm_default_connector_id: null` also clears the default
    # - otherwise, llm_default_connector_id (if non-None) is validated and set
    explicit_null_default = (
        "llm_default_connector_id" in payload.model_fields_set
        and payload.llm_default_connector_id is None
    )
    if payload.clear_default or explicit_null_default:
        update_kwargs["llm_default_connector_id"] = None
    elif payload.llm_default_connector_id is not None:
        target = get_connector(db, payload.llm_default_connector_id)
        if target is None:
            raise HTTPException(status_code=400, detail="default connector not found")
        if target.status != "active":
            raise HTTPException(
                status_code=400,
                detail="default connector must be active",
            )
        if target.scope != "org":
            raise HTTPException(
                status_code=400,
                detail=(
                    "default connector must be org-scoped — create an Organization connector first"
                ),
            )
        update_kwargs["llm_default_connector_id"] = target.id

    settings = update_system_settings(db, **update_kwargs)
    audit_event(
        db,
        actor_user_id=admin.id,
        target_connector_id=settings.llm_default_connector_id,
        event_type=AUDIT_POLICY_CHANGED,
    )
    db.commit()
    return AdminPolicyOut(
        llm_apikey_connectors_enabled=settings.llm_apikey_connectors_enabled,
        llm_compatible_connector_enabled=settings.llm_compatible_connector_enabled,
        llm_default_connector_id=settings.llm_default_connector_id,
        llm_call_log_retention_days=settings.llm_call_log_retention_days,
    )


@router.get("/connectors", response_model=list[AdminConnectorOut])
@limiter.limit("60/minute")
def list_connectors_admin(
    request: FastAPIRequest,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[AdminConnectorOut]:
    rows = list_all_connectors(db)
    user_ids = {r.user_id for r in rows if r.user_id is not None}
    usernames: dict[int, str] = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        usernames = {u.id: u.username for u in users}

    # One grouped aggregate for all connectors instead of an N+1 per-row query.
    usage_by_connector = current_month_token_usage_bulk(db, [r.id for r in rows])

    return [
        _connector_to_admin_out(
            r,
            owner_label(r.user_id, usernames),
            usage_by_connector.get(r.id, 0),
        )
        for r in rows
    ]


@router.post("/connectors/{connector_id}/revoke", response_model=AdminConnectorOut)
@limiter.limit("30/minute")
def revoke_connector_admin(
    request: FastAPIRequest,
    connector_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminConnectorOut:
    row = get_connector(db, connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    revoke_connector(row)
    audit_event(
        db,
        actor_user_id=admin.id,
        target_connector_id=row.id,
        event_type=AUDIT_REVOKED_BY_ADMIN,
    )

    # If the revoked connector was the system default, clear it.
    settings = get_system_settings(db)
    if settings.llm_default_connector_id == row.id:
        settings.llm_default_connector_id = None

    db.commit()
    db.refresh(row)
    return _connector_to_admin_out(
        row, get_user_label(db, row.user_id), current_month_token_usage(db, row.id)
    )


@router.patch("/connectors/{connector_id}/cap", response_model=AdminConnectorOut)
@limiter.limit("30/minute")
def set_connector_cap_admin(
    request: FastAPIRequest,
    connector_id: int,
    payload: AdminConnectorCapPatch,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminConnectorOut:
    """Set or clear a connector's monthly token cap (admin-only, issue #339).

    ``monthly_token_cap = null`` clears the cap (unlimited). The change is
    pre-flight only: an in-flight gateway call already past its cap check is
    unaffected. Pydantic enforces the non-negative bound (``ge=0``); the
    service layer re-validates defensively.
    """
    row = get_connector(db, connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    try:
        set_monthly_cap(row, payload.monthly_token_cap)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        db,
        actor_user_id=admin.id,
        target_connector_id=row.id,
        event_type=AUDIT_POLICY_CHANGED,
    )
    db.commit()
    db.refresh(row)
    return _connector_to_admin_out(
        row, get_user_label(db, row.user_id), current_month_token_usage(db, row.id)
    )


@router.get("/usage", response_model=AdminUsageOut)
@limiter.limit("30/minute")
def get_usage(
    request: FastAPIRequest,
    days: int = Query(default=30, ge=1, le=180),
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminUsageOut:
    rows = get_usage_stats(db, days=days)
    rows_out: list[UsageRow] = []
    if rows:
        connector_ids = [r["connector_id"] for r in rows]
        connectors = db.query(LlmConnector).filter(LlmConnector.id.in_(connector_ids)).all()
        connector_map = {c.id: c for c in connectors}
        user_ids = {c.user_id for c in connectors if c.user_id is not None}
        users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
        usernames = {u.id: u.username for u in users}

        for r in rows:
            cid = r["connector_id"]
            c = connector_map.get(cid)
            if c is None:
                continue
            total = r["total_calls"]
            errors = r["error_count"]
            rows_out.append(
                UsageRow(
                    connector_id=cid,
                    dj_username=owner_label(c.user_id, usernames),
                    display_name=c.display_name,
                    connector_type=c.connector_type,  # type: ignore[arg-type]
                    total_calls=total,
                    total_tokens_in=r["total_tokens_in"],
                    total_tokens_out=r["total_tokens_out"],
                    error_count=errors,
                    error_rate=(errors / total) if total else 0.0,
                )
            )
    # Sort: most calls first, then by error rate desc as tiebreaker
    rows_out.sort(key=lambda r: (-r.total_calls, -r.error_rate))
    return AdminUsageOut(days=days, rows=rows_out)


@router.get("/audit", response_model=AdminAuditOut)
@limiter.limit("60/minute")
def list_audit_events(
    request: FastAPIRequest,
    event_type: str | None = Query(default=None, max_length=60),
    actor_user_id: int | None = Query(default=None, ge=1),
    target_connector_id: int | None = Query(default=None, ge=1),
    days: int = Query(default=30, ge=1, le=3650),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminAuditOut:
    """Browse the LLM audit trail (admin-only).

    Read-only view over ``llm_audit_event`` with optional filters and
    pagination. The target connector's display name is joined in — credential
    material is never read or returned.
    """
    base = _audit_query(
        db,
        event_type=event_type,
        actor_user_id=actor_user_id,
        target_connector_id=target_connector_id,
        days=days,
    )

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    page = (
        base.order_by(LlmAuditEvent.created_at.desc(), LlmAuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )

    rows_out: list[AuditEventRow] = []
    for event, actor_username, connector_display_name in db.execute(page).all():
        rows_out.append(
            AuditEventRow(
                id=event.id,
                created_at=event.created_at,
                event_type=event.event_type,
                actor_user_id=event.actor_user_id,
                actor_username=_actor_label(event, actor_username),
                target_connector_id=event.target_connector_id,
                target_connector_display_name=connector_display_name,
                notes=None,
            )
        )

    return AdminAuditOut(rows=rows_out, total=int(total), limit=limit, offset=offset)


@router.get(
    "/audit.csv",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
            "description": "CSV export of the filtered audit trail.",
        }
    },
)
@limiter.limit("12/minute")
def export_audit_events_csv(
    request: FastAPIRequest,
    event_type: str | None = Query(default=None, max_length=60),
    actor_user_id: int | None = Query(default=None, ge=1),
    target_connector_id: int | None = Query(default=None, ge=1),
    days: int = Query(default=30, ge=1, le=3650),
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export the (filtered) audit trail as CSV (admin-only).

    Honors the same filters as ``GET /audit``. Capped at
    ``_AUDIT_CSV_ROW_CAP`` rows to avoid unbounded streaming. Columns:
    timestamp, actor, actor_user_id, event_type, target_connector, notes.
    ``actor_user_id`` is empty for system rows, so a DJ literally named
    "system" can never be confused with the NULL-actor system label. Never
    includes credential material.
    """
    stmt = (
        _audit_query(
            db,
            event_type=event_type,
            actor_user_id=actor_user_id,
            target_connector_id=target_connector_id,
            days=days,
        )
        .order_by(LlmAuditEvent.created_at.desc(), LlmAuditEvent.id.desc())
        .limit(_AUDIT_CSV_ROW_CAP)
    )
    result_rows = db.execute(stmt).all()

    def _generate() -> Iterator[str]:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["timestamp", "actor", "actor_user_id", "event_type", "target_connector", "notes"]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        for event, actor_username, connector_display_name in result_rows:
            writer.writerow(
                [
                    event.created_at.isoformat() if event.created_at else "",
                    sanitize_csv_value(_actor_label(event, actor_username)),
                    "" if event.actor_user_id is None else str(event.actor_user_id),
                    sanitize_csv_value(event.event_type or ""),
                    sanitize_csv_value(connector_display_name or ""),
                    "",
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    headers = {"Content-Disposition": 'attachment; filename="llm-audit-events.csv"'}
    return StreamingResponse(_generate(), media_type="text/csv", headers=headers)


# ---------- Organization connector (house-billed fallback) ----------


@router.get("/org-connectors", response_model=list[ConnectorOut])
@limiter.limit("60/minute")
def list_org_connectors_admin(
    request: FastAPIRequest,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[ConnectorOut]:
    return [ConnectorOut.model_validate(r) for r in list_org_connectors(db)]


@router.post("/org-connectors", response_model=ConnectorOut, status_code=201)
@limiter.limit("10/minute")
def create_org_connector(
    request: FastAPIRequest,
    payload: ConnectorCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    """Create the organization's house connector (admin-only).

    Reuses the DJ-connector validation pipeline; the row is org-scoped with no
    owner. Credentials are encrypted at rest via EncryptedText. The DJ-facing
    connector-type policy toggles are not applied — org connectors are an
    admin decision.
    """
    try:
        create_payload = build_create_payload(
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
        row = create_connector(db, user_id=None, payload=create_payload, scope="org")
    except ValueError as exc:
        # Field validation failures + the org duplicate-(type, label) guard.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_event(db, actor_user_id=admin.id, target_connector_id=row.id, event_type=AUDIT_CREATED)
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row)


@router.post("/org-connectors/{connector_id}/test", response_model=ConnectorTestResult)
@limiter.limit("10/minute")
async def test_org_connector(
    request: FastAPIRequest,
    connector_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> ConnectorTestResult:
    """Run a health check against an org connector and return a sanitised result.

    Mirrors the DJ-facing ``POST /api/llm/connectors/{id}/test`` — same shared
    helper, same status columns and audit rows, same code → message mapping.
    """
    from app.services.llm.health_check import run_health_check

    row = _get_org_connector_or_404(db, connector_id)

    outcome = await run_health_check(db, row, actor_user_id=admin.id)
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


@router.put("/org-connectors/{connector_id}/credentials", response_model=ConnectorOut)
@limiter.limit("10/minute")
def rotate_org_connector_credentials(
    request: FastAPIRequest,
    connector_id: int,
    payload: ConnectorCredentialsRotate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> ConnectorOut:
    row = _get_org_connector_or_404(db, connector_id)

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
        actor_user_id=admin.id,
        target_connector_id=row.id,
        event_type=AUDIT_CREDENTIALS_ROTATED,
    )
    db.commit()
    db.refresh(row)
    return ConnectorOut.model_validate(row)


@router.delete("/org-connectors/{connector_id}", status_code=204)
@limiter.limit("10/minute")
def delete_org_connector(
    request: FastAPIRequest,
    connector_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    row = _get_org_connector_or_404(db, connector_id)
    audit_event(db, actor_user_id=admin.id, target_connector_id=row.id, event_type=AUDIT_DELETED)
    # If this connector is the system default, clear it before deletion (and to
    # be correct on SQLite, where the FK ON DELETE SET NULL may not fire).
    settings = get_system_settings(db)
    if settings.llm_default_connector_id == row.id:
        settings.llm_default_connector_id = None
    delete_connector(db, row)
    db.commit()
