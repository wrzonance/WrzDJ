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
    AdminConnectorOut,
    AdminPolicyOut,
    AdminPolicyPatch,
    AdminUsageOut,
    AuditEventRow,
    UsageRow,
)
from app.services.llm.connector_storage import (
    AUDIT_POLICY_CHANGED,
    AUDIT_REVOKED_BY_ADMIN,
    audit_event,
    get_connector,
    get_usage_stats,
    get_user_label,
    list_all_connectors,
    revoke_connector,
)
from app.services.system_settings import get_system_settings, update_system_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Hard ceiling for a single CSV export — keeps an attacker (or an honest admin
# with a huge history) from streaming an unbounded result set.
_AUDIT_CSV_ROW_CAP = 10_000


def _connector_to_admin_out(row: LlmConnector, dj_username: str) -> AdminConnectorOut:
    """Reflect a connector row + its owner's display name into the admin view.

    ``AdminConnectorOut`` adds ``dj_username``, which isn't a column on the row,
    so the model is validated from a column-reflection dict rather than the ORM
    object directly.
    """
    return AdminConnectorOut.model_validate(
        {
            **{c.name: getattr(row, c.name) for c in LlmConnector.__table__.columns},
            "dj_username": dj_username,
        }
    )


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
    user_ids = {r.user_id for r in rows}
    usernames: dict[int, str] = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        usernames = {u.id: u.username for u in users}

    return [
        _connector_to_admin_out(r, usernames.get(r.user_id) or f"user#{r.user_id}") for r in rows
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
    return _connector_to_admin_out(row, get_user_label(db, row.user_id))


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
        user_ids = {c.user_id for c in connectors}
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
                    dj_username=usernames.get(c.user_id, f"user#{c.user_id}"),
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
                actor_username=actor_username or f"user#{event.actor_user_id}",
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
    timestamp, actor, event_type, target_connector, notes. Never includes
    credential material.
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
        writer.writerow(["timestamp", "actor", "event_type", "target_connector", "notes"])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        for event, actor_username, connector_display_name in result_rows:
            actor = actor_username or f"user#{event.actor_user_id}"
            writer.writerow(
                [
                    event.created_at.isoformat() if event.created_at else "",
                    sanitize_csv_value(actor),
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
