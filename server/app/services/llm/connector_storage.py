"""SQLAlchemy CRUD helpers for LlmConnector + audit/call logging."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.llm_connector import (
    AUDIT_AUTH_INVALID_OBSERVED,
    AUDIT_CREATED,
    AUDIT_CREDENTIALS_ROTATED,
    AUDIT_DEFAULT_SET,
    AUDIT_DEFAULT_UNSET,
    AUDIT_DELETED,
    AUDIT_HEALTH_CHECK,
    AUDIT_POLICY_CHANGED,
    AUDIT_REVOKED_BY_ADMIN,
    SCOPE_ORG,
    SCOPE_USER,
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    STATUS_DISABLED,
    LlmConnector,
)
from app.services.llm.connector_payloads import (
    CreateConnectorPayload,
    CredentialRotationInput,
    build_rotated_credentials,
    normalize_model_hint,
)
from app.services.llm.connector_telemetry import (
    audit_event,
    current_month_token_usage,
    current_month_token_usage_bulk,
    get_usage_stats,
    get_user_label,
    log_call,
    owner_label,
    purge_call_log_older_than,
)


def list_connectors_for_user(db: Session, user_id: int) -> list[LlmConnector]:
    return (
        db.query(LlmConnector)
        .filter(LlmConnector.user_id == user_id, LlmConnector.scope == SCOPE_USER)
        .order_by(LlmConnector.created_at.desc())
        .all()
    )


def list_all_connectors(db: Session) -> list[LlmConnector]:
    return (
        db.query(LlmConnector)
        .order_by(LlmConnector.user_id.asc(), LlmConnector.created_at.desc())
        .all()
    )


def list_org_connectors(db: Session) -> list[LlmConnector]:
    return (
        db.query(LlmConnector)
        .filter(LlmConnector.scope == SCOPE_ORG)
        .order_by(LlmConnector.created_at.desc())
        .all()
    )


def get_connector_for_user(db: Session, connector_id: int, user_id: int) -> LlmConnector | None:
    return (
        db.query(LlmConnector)
        .filter(LlmConnector.id == connector_id, LlmConnector.user_id == user_id)
        .one_or_none()
    )


def get_connector(db: Session, connector_id: int) -> LlmConnector | None:
    return db.get(LlmConnector, connector_id)


def create_connector(
    db: Session,
    *,
    user_id: int | None,
    payload: CreateConnectorPayload,
    scope: str = SCOPE_USER,
) -> LlmConnector:
    """Persist a new connector. Caller is responsible for audit event + commit.

    Org-scoped rows (scope='org') must pass user_id=None — the DB CHECK
    enforces it; this guard catches programming errors early. Org rows are
    exempt from the per-user unique label constraint (NULL user_id rows are
    NULLS-DISTINCT on Postgres), so duplicate org labels are rejected here.
    """
    if (scope == SCOPE_ORG) != (user_id is None):
        raise ValueError("org scope requires user_id=None; user scope requires a user_id")
    if scope == SCOPE_ORG:
        duplicate = (
            db.query(LlmConnector.id)
            .filter(
                LlmConnector.scope == SCOPE_ORG,
                LlmConnector.connector_type == payload.connector_type,
                LlmConnector.display_name == payload.display_name,
            )
            .first()
        )
        if duplicate is not None:
            raise ValueError("An org connector with this label already exists")
    row = LlmConnector(
        user_id=user_id,
        scope=scope,
        connector_type=payload.connector_type,
        display_name=payload.display_name,
        status=STATUS_ACTIVE,
        credentials=json.dumps(payload.credentials),
        base_url_plain=payload.base_url_plain,
        model_hint=payload.model_hint,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def rotate_credentials(
    db: Session,
    *,
    connector: LlmConnector,
    rotation: CredentialRotationInput,
) -> LlmConnector:
    """Rotate the credential blob in-place. Caller commits."""
    payload = build_rotated_credentials(
        connector.connector_type,
        connector.credentials,
        rotation,
    )
    connector.credentials = json.dumps(payload.credentials)
    if payload.base_url_plain is not None:
        connector.base_url_plain = payload.base_url_plain
    # Clear status/last_error on successful rotation — caller may run a fresh health check.
    if connector.status == STATUS_AUTH_INVALID:
        connector.status = STATUS_ACTIVE
        connector.last_error = None
    return connector


def update_connector_metadata(
    connector: LlmConnector,
    *,
    display_name: str | None = None,
    model_hint: str | None = None,
) -> LlmConnector:
    if display_name is not None:
        display_name = display_name.strip()
        if not display_name:
            raise ValueError("display_name is required")
        if len(display_name) > 80:
            raise ValueError("display_name must be 80 characters or fewer")
        if any(ord(c) < 0x20 for c in display_name):
            raise ValueError("display_name must not contain control characters")
        connector.display_name = display_name
    if model_hint is not None:
        connector.model_hint = normalize_model_hint(
            model_hint, invalid_msg="model_hint contains invalid characters"
        )
    return connector


def delete_connector(db: Session, connector: LlmConnector) -> None:
    db.delete(connector)


def set_default_for_user(db: Session, *, connector: LlmConnector) -> LlmConnector:
    """Mark ``connector`` as the DJ's default and clear any sibling defaults.

    Atomic clear-then-set: all other rows for ``connector.user_id`` are flipped
    to ``is_default = False`` in a single UPDATE before the target row is
    flipped to True. This sidesteps the partial unique index race that would
    otherwise occur if two SET requests landed concurrently — the worst case
    is the second request overwriting the first, which is the user's intent.
    The caller commits and writes the audit event.

    No-ops gracefully when ``connector.is_default`` is already True (the
    sibling clear still runs to fix any drift, e.g. a stale row left behind
    by an aborted migration backfill).
    """
    db.query(LlmConnector).filter(
        LlmConnector.user_id == connector.user_id,
        LlmConnector.id != connector.id,
        LlmConnector.is_default == True,  # noqa: E712
    ).update({LlmConnector.is_default: False}, synchronize_session=False)
    connector.is_default = True
    db.flush()
    return connector


def unset_default_for_user(db: Session, *, connector: LlmConnector) -> LlmConnector:
    """Clear the explicit-default flag. Caller commits + audits."""
    connector.is_default = False
    db.flush()
    return connector


def revoke_connector(connector: LlmConnector) -> LlmConnector:
    """Admin-only: mark a connector disabled. Caller commits + audits."""
    connector.status = STATUS_DISABLED
    return connector


def set_monthly_cap(connector: LlmConnector, cap: int | None) -> LlmConnector:
    """Set (or clear) the connector's monthly token cap. Caller commits.

    ``cap=None`` clears the cap (unlimited). A non-None cap must be a
    non-negative integer; negative values are rejected with ``ValueError``
    (→ HTTP 400 at the API boundary).
    """
    if cap is not None and cap < 0:
        raise ValueError("monthly_token_cap must be a non-negative integer or null")
    connector.monthly_token_cap = cap
    return connector


# Re-export audit event constants for callers
__all__ = [
    "AUDIT_AUTH_INVALID_OBSERVED",
    "AUDIT_CREATED",
    "AUDIT_CREDENTIALS_ROTATED",
    "AUDIT_DEFAULT_SET",
    "AUDIT_DEFAULT_UNSET",
    "AUDIT_DELETED",
    "AUDIT_HEALTH_CHECK",
    "AUDIT_POLICY_CHANGED",
    "AUDIT_REVOKED_BY_ADMIN",
    "audit_event",
    "create_connector",
    "current_month_token_usage",
    "current_month_token_usage_bulk",
    "delete_connector",
    "get_connector",
    "get_connector_for_user",
    "get_usage_stats",
    "get_user_label",
    "list_all_connectors",
    "list_connectors_for_user",
    "list_org_connectors",
    "log_call",
    "owner_label",
    "purge_call_log_older_than",
    "revoke_connector",
    "rotate_credentials",
    "set_default_for_user",
    "set_monthly_cap",
    "unset_default_for_user",
    "update_connector_metadata",
]
