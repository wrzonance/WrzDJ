"""Admin LLM policy + connector oversight endpoints.

Authentication: ``get_current_admin``.
Routes are mounted at ``/api/admin/llm``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Request as FastAPIRequest
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_db
from app.core.rate_limit import limiter
from app.models.llm_connector import LlmConnector
from app.models.user import User
from app.schemas.llm import (
    AdminConnectorOut,
    AdminPolicyOut,
    AdminPolicyPatch,
    AdminUsageOut,
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

    # Default connector handling:
    # - clear_default=True takes precedence and sets to NULL
    # - otherwise, llm_default_connector_id (if non-None) is validated and set
    if payload.clear_default:
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

    out: list[AdminConnectorOut] = []
    for r in rows:
        payload = AdminConnectorOut.model_validate(
            {
                **{c.name: getattr(r, c.name) for c in LlmConnector.__table__.columns},
                "dj_username": usernames.get(r.user_id) or f"user#{r.user_id}",
            }
        )
        out.append(payload)
    return out


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
    return AdminConnectorOut.model_validate(
        {
            **{c.name: getattr(row, c.name) for c in LlmConnector.__table__.columns},
            "dj_username": get_user_label(db, row.user_id),
        }
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
