"""SQLAlchemy CRUD helpers for LlmConnector + audit/call logging."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.llm_connector import (
    AUDIT_AUTH_INVALID_OBSERVED,
    AUDIT_CREATED,
    AUDIT_CREDENTIALS_ROTATED,
    AUDIT_DELETED,
    AUDIT_HEALTH_CHECK,
    AUDIT_POLICY_CHANGED,
    AUDIT_REVOKED_BY_ADMIN,
    CONNECTOR_TYPE_ANTHROPIC_APIKEY,
    CONNECTOR_TYPE_OPENAI_APIKEY,
    CONNECTOR_TYPE_OPENAI_COMPATIBLE,
    CONNECTOR_TYPE_OPENROUTER_APIKEY,
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    STATUS_DISABLED,
    VALID_CONNECTOR_TYPES,
    LlmAuditEvent,
    LlmCallLog,
    LlmConnector,
)
from app.models.user import User
from app.services.llm.url_validator import (
    InvalidBaseUrlError,
    validate_compatible_base_url,
)

logger = logging.getLogger(__name__)


def list_connectors_for_user(db: Session, user_id: int) -> list[LlmConnector]:
    return (
        db.query(LlmConnector)
        .filter(LlmConnector.user_id == user_id)
        .order_by(LlmConnector.created_at.desc())
        .all()
    )


def list_all_connectors(db: Session) -> list[LlmConnector]:
    return (
        db.query(LlmConnector)
        .order_by(LlmConnector.user_id.asc(), LlmConnector.created_at.desc())
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


class CreateConnectorPayload:
    """Validated creation payload — see :func:`create_connector`."""

    __slots__ = ("connector_type", "display_name", "credentials", "base_url_plain", "model_hint")

    def __init__(
        self,
        *,
        connector_type: str,
        display_name: str,
        credentials: dict,
        base_url_plain: str | None = None,
        model_hint: str | None = None,
    ) -> None:
        self.connector_type = connector_type
        self.display_name = display_name
        self.credentials = credentials
        self.base_url_plain = base_url_plain
        self.model_hint = model_hint


def build_create_payload(
    *,
    connector_type: str,
    display_name: str,
    api_key: str | None = None,
    base_url: str | None = None,
    bearer: str | None = None,
    model_hint: str | None = None,
) -> CreateConnectorPayload:
    """Translate request fields into a validated ``CreateConnectorPayload``.

    Raises :class:`ValueError` on validation errors. The caller is responsible
    for returning a 400 to the client.
    """
    if connector_type not in VALID_CONNECTOR_TYPES:
        raise ValueError(f"Unknown connector_type: {connector_type!r}")

    display_name = (display_name or "").strip()
    if not display_name:
        raise ValueError("display_name is required")
    if len(display_name) > 80:
        raise ValueError("display_name must be 80 characters or fewer")
    if any(ord(c) < 0x20 for c in display_name):
        raise ValueError("display_name must not contain control characters")

    if model_hint is not None:
        model_hint = model_hint.strip() or None
        if model_hint is not None:
            if len(model_hint) > 80:
                raise ValueError("model_hint must be 80 characters or fewer")
            if not _is_safe_model_hint(model_hint):
                raise ValueError(
                    "model_hint may only contain letters, digits, dot, underscore, hyphen, or slash"
                )

    creds: dict[str, Any]
    plain_base_url: str | None = None

    if connector_type in (
        CONNECTOR_TYPE_OPENAI_APIKEY,
        CONNECTOR_TYPE_ANTHROPIC_APIKEY,
        CONNECTOR_TYPE_OPENROUTER_APIKEY,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        api_key = api_key.strip()
        if not _looks_like_api_key(connector_type, api_key):
            raise ValueError("api_key format is invalid")
        creds = {"api_key": api_key}
    elif connector_type == CONNECTOR_TYPE_OPENAI_COMPATIBLE:
        if not base_url:
            raise ValueError("base_url is required")
        try:
            plain_base_url = validate_compatible_base_url(base_url)
        except InvalidBaseUrlError as exc:
            raise ValueError(str(exc)) from exc
        creds = {"base_url": plain_base_url, "bearer": bearer or None}
    else:  # pragma: no cover — guarded by the membership check above
        raise ValueError(f"Unsupported connector_type: {connector_type!r}")

    return CreateConnectorPayload(
        connector_type=connector_type,
        display_name=display_name,
        credentials=creds,
        base_url_plain=plain_base_url,
        model_hint=model_hint,
    )


_OPENAI_KEY_PREFIXES = ("sk-",)
_ANTHROPIC_KEY_PREFIX = "sk-ant-"
_OPENROUTER_KEY_PREFIX = "sk-or-"
_SAFE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
# Slash is permitted so namespaced model ids (e.g. OpenRouter's
# "provider/model") validate. The hint is only ever sent as the request-body
# "model" field — never used to build a filesystem/URL path.
_SAFE_MODEL_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./")


def _is_safe_model_hint(s: str) -> bool:
    return all(c in _SAFE_MODEL_CHARS for c in s)


def _looks_like_api_key(connector_type: str, key: str) -> bool:
    """Cheap shape check — full validation is on the upstream API at health-check time."""
    if not key or " " in key or "\n" in key:
        return False
    if not all(c in _SAFE_CHARS for c in key):
        return False
    if connector_type == CONNECTOR_TYPE_ANTHROPIC_APIKEY:
        return key.startswith(_ANTHROPIC_KEY_PREFIX) and len(key) >= len(_ANTHROPIC_KEY_PREFIX) + 30
    if connector_type == CONNECTOR_TYPE_OPENROUTER_APIKEY:
        min_len = len(_OPENROUTER_KEY_PREFIX) + 20
        return key.startswith(_OPENROUTER_KEY_PREFIX) and len(key) >= min_len
    if connector_type == CONNECTOR_TYPE_OPENAI_APIKEY:
        return any(key.startswith(p) for p in _OPENAI_KEY_PREFIXES) and len(key) >= 20
    return False


def create_connector(db: Session, *, user_id: int, payload: CreateConnectorPayload) -> LlmConnector:
    """Persist a new connector. Caller is responsible for audit event + commit."""
    row = LlmConnector(
        user_id=user_id,
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
    api_key: str | None = None,
    base_url: str | None = None,
    bearer: str | None = None,
) -> LlmConnector:
    """Rotate the credential blob in-place. Caller commits."""
    blob: dict[str, Any]
    if connector.connector_type in (
        CONNECTOR_TYPE_OPENAI_APIKEY,
        CONNECTOR_TYPE_ANTHROPIC_APIKEY,
        CONNECTOR_TYPE_OPENROUTER_APIKEY,
    ):
        if not api_key:
            raise ValueError("api_key is required for rotation")
        api_key = api_key.strip()
        if not _looks_like_api_key(connector.connector_type, api_key):
            raise ValueError("api_key format is invalid")
        blob = {"api_key": api_key}
    elif connector.connector_type == CONNECTOR_TYPE_OPENAI_COMPATIBLE:
        if not base_url:
            raise ValueError("base_url is required for rotation")
        try:
            base_url = validate_compatible_base_url(base_url)
        except InvalidBaseUrlError as exc:
            raise ValueError(str(exc)) from exc
        blob = {"base_url": base_url, "bearer": bearer or None}
        connector.base_url_plain = base_url
    else:  # pragma: no cover
        raise ValueError(f"Unsupported connector_type: {connector.connector_type!r}")

    connector.credentials = json.dumps(blob)
    # Clear status/last_error on successful rotation — caller may run a fresh health check.
    if connector.status == STATUS_AUTH_INVALID:
        connector.status = STATUS_ACTIVE
        connector.last_error = None
    return connector


def update_metadata(
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
        model_hint = model_hint.strip() or None
        if model_hint is not None:
            if len(model_hint) > 80:
                raise ValueError("model_hint must be 80 characters or fewer")
            if not _is_safe_model_hint(model_hint):
                raise ValueError("model_hint contains invalid characters")
        connector.model_hint = model_hint
    return connector


def delete_connector(db: Session, connector: LlmConnector) -> None:
    db.delete(connector)


def revoke_connector(connector: LlmConnector) -> LlmConnector:
    """Admin-only: mark a connector disabled. Caller commits + audits."""
    connector.status = STATUS_DISABLED
    return connector


def audit_event(
    db: Session,
    *,
    actor_user_id: int,
    target_connector_id: int | None,
    event_type: str,
) -> LlmAuditEvent:
    row = LlmAuditEvent(
        actor_user_id=actor_user_id,
        target_connector_id=target_connector_id,
        event_type=event_type,
    )
    db.add(row)
    db.flush()
    return row


def log_call(
    db: Session,
    *,
    connector_id: int,
    purpose: str,
    status: str,
    latency_ms: int,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    error_code: str | None = None,
) -> LlmCallLog:
    row = LlmCallLog(
        connector_id=connector_id,
        purpose=purpose,
        status=status,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        error_code=error_code,
    )
    db.add(row)
    db.flush()
    return row


def get_user_label(db: Session, user_id: int) -> str:
    user = db.get(User, user_id)
    return user.username if user else f"user#{user_id}"


def get_usage_stats(db: Session, *, days: int = 30) -> list[dict]:
    """Aggregate per-connector telemetry for the admin Usage card.

    Returns a list of dicts with: connector_id, total_calls, total_tokens_in,
    total_tokens_out, error_count. The caller joins back to LlmConnector for
    display labels.
    """
    from datetime import timedelta

    from app.core.time import utcnow

    cutoff = utcnow() - timedelta(days=days)

    stmt = (
        select(
            LlmCallLog.connector_id,
            func.count(LlmCallLog.id).label("total_calls"),
            func.coalesce(func.sum(LlmCallLog.tokens_in), 0).label("total_tokens_in"),
            func.coalesce(func.sum(LlmCallLog.tokens_out), 0).label("total_tokens_out"),
            func.sum(case((LlmCallLog.status != "ok", 1), else_=0)).label("error_count"),
        )
        .where(LlmCallLog.created_at >= cutoff)
        .group_by(LlmCallLog.connector_id)
    )
    rows = db.execute(stmt).all()
    return [
        {
            "connector_id": int(r.connector_id),
            "total_calls": int(r.total_calls or 0),
            "total_tokens_in": int(r.total_tokens_in or 0),
            "total_tokens_out": int(r.total_tokens_out or 0),
            "error_count": int(r.error_count or 0),
        }
        for r in rows
    ]


# Re-export audit event constants for callers
__all__ = [
    "AUDIT_AUTH_INVALID_OBSERVED",
    "AUDIT_CREATED",
    "AUDIT_CREDENTIALS_ROTATED",
    "AUDIT_DELETED",
    "AUDIT_HEALTH_CHECK",
    "AUDIT_POLICY_CHANGED",
    "AUDIT_REVOKED_BY_ADMIN",
    "CreateConnectorPayload",
    "audit_event",
    "build_create_payload",
    "create_connector",
    "delete_connector",
    "get_connector",
    "get_connector_for_user",
    "get_usage_stats",
    "get_user_label",
    "list_all_connectors",
    "list_connectors_for_user",
    "log_call",
    "revoke_connector",
    "rotate_credentials",
    "update_metadata",
]
