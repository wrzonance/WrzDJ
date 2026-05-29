"""SQLAlchemy CRUD helpers for LlmConnector + audit/call logging."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import case, delete, func, select
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
    CONNECTOR_TYPE_ANTHROPIC_APIKEY,
    CONNECTOR_TYPE_AZURE_OPENAI,
    CONNECTOR_TYPE_BEDROCK,
    CONNECTOR_TYPE_GEMINI_APIKEY,
    CONNECTOR_TYPE_OPENAI_APIKEY,
    CONNECTOR_TYPE_OPENAI_COMPATIBLE,
    CONNECTOR_TYPE_OPENROUTER_APIKEY,
    CONNECTOR_TYPE_XAI_APIKEY,
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


# API-key connector types (shared by the create + rotate validation dispatch).
_APIKEY_CONNECTOR_TYPES = (
    CONNECTOR_TYPE_OPENAI_APIKEY,
    CONNECTOR_TYPE_ANTHROPIC_APIKEY,
    CONNECTOR_TYPE_OPENROUTER_APIKEY,
    CONNECTOR_TYPE_XAI_APIKEY,
    CONNECTOR_TYPE_GEMINI_APIKEY,
)


def _normalise_model_hint(value: str | None, *, invalid_msg: str) -> str | None:
    """Strip + validate a model_hint (≤80 chars, safe charset). ``invalid_msg``
    stays caller-supplied so create vs update keep their distinct error text."""
    if value is None:
        return None
    value = value.strip() or None
    if value is not None:
        if len(value) > 80:
            raise ValueError("model_hint must be 80 characters or fewer")
        if not _is_safe_model_hint(value):
            raise ValueError(invalid_msg)
    return value


def _validate_api_key_blob(connector_type: str, api_key: str | None, *, required_msg: str) -> dict:
    """Validate + assemble an ``{"api_key": ...}`` blob. ``required_msg`` differs
    between create and rotate, so it stays caller-supplied."""
    if not api_key:
        raise ValueError(required_msg)
    api_key = api_key.strip()
    if not _looks_like_api_key(connector_type, api_key):
        raise ValueError("api_key format is invalid")
    return {"api_key": api_key}


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
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_region: str | None = None,
    aws_model_id: str | None = None,
    azure_resource_name: str | None = None,
    azure_deployment_name: str | None = None,
    azure_api_version: str | None = None,
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

    model_hint = _normalise_model_hint(
        model_hint,
        invalid_msg=(
            "model_hint may only contain letters, digits, dot, underscore, hyphen, or slash"
        ),
    )

    creds: dict[str, Any]
    plain_base_url: str | None = None

    if connector_type in _APIKEY_CONNECTOR_TYPES:
        creds = _validate_api_key_blob(connector_type, api_key, required_msg="api_key is required")
    elif connector_type == CONNECTOR_TYPE_OPENAI_COMPATIBLE:
        if not base_url:
            raise ValueError("base_url is required")
        try:
            plain_base_url = validate_compatible_base_url(base_url)
        except InvalidBaseUrlError as exc:
            raise ValueError(str(exc)) from exc
        creds = {"base_url": plain_base_url, "bearer": bearer or None}
    elif connector_type == CONNECTOR_TYPE_BEDROCK:
        creds = _build_bedrock_creds(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_region=aws_region,
            aws_model_id=aws_model_id,
        )
    elif connector_type == CONNECTOR_TYPE_AZURE_OPENAI:
        if not api_key:
            raise ValueError("api_key is required")
        api_key = api_key.strip()
        creds = _build_azure_creds(
            api_key=api_key,
            azure_resource_name=azure_resource_name,
            azure_deployment_name=azure_deployment_name,
            azure_api_version=azure_api_version,
        )
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
_XAI_KEY_PREFIX = "xai-"
# Google AI Studio (Gemini) keys are "AIza" + 35 url-safe chars = 39 total.
_GEMINI_KEY_PREFIX = "AIza"
_GEMINI_KEY_LENGTH = 39
_SAFE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
# Slash is permitted so namespaced model ids (e.g. OpenRouter's
# "provider/model") validate. The hint is only ever sent as the request-body
# "model" field — never used to build a filesystem/URL path.
_SAFE_MODEL_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./")


def _is_safe_model_hint(s: str) -> bool:
    return all(c in _SAFE_MODEL_CHARS for c in s)


# AWS region tokens are lowercase alnum + hyphen (e.g. us-east-1, eu-central-1).
_AWS_REGION_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")
# Bedrock model ids look like "anthropic.claude-3-5-sonnet-20241022-v2:0" or
# "meta.llama3-70b-instruct-v1:0" — allow the inference-profile/ARN-ish chars.
_AWS_MODEL_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:/")


def _build_bedrock_creds(
    *,
    aws_access_key_id: str | None,
    aws_secret_access_key: str | None,
    aws_region: str | None,
    aws_model_id: str | None,
) -> dict[str, str]:
    """Validate + assemble the bedrock credentials blob.

    Raises :class:`ValueError` (→ HTTP 400) on any malformed field. No AWS
    dependency: the access key id / secret are opaque strings; we only sanity
    check shape and reject obviously-bad input before persisting.
    """
    access_key = (aws_access_key_id or "").strip()
    secret_key = (aws_secret_access_key or "").strip()
    region = (aws_region or "").strip()
    model_id = (aws_model_id or "").strip()

    if not access_key:
        raise ValueError("aws_access_key_id is required")
    if not secret_key:
        raise ValueError("aws_secret_access_key is required")
    if not region:
        raise ValueError("aws_region is required")
    if not model_id:
        raise ValueError("aws_model_id is required")

    if " " in access_key or "\n" in access_key or not all(c in _SAFE_CHARS for c in access_key):
        raise ValueError("aws_access_key_id format is invalid")
    if " " in secret_key or "\n" in secret_key:
        raise ValueError("aws_secret_access_key format is invalid")
    if not all(c in _AWS_REGION_CHARS for c in region):
        raise ValueError("aws_region format is invalid")
    if not all(c in _AWS_MODEL_ID_CHARS for c in model_id):
        raise ValueError("aws_model_id format is invalid")

    return {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "aws_region": region,
        "aws_model_id": model_id,
    }


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
    if connector_type == CONNECTOR_TYPE_XAI_APIKEY:
        return key.startswith(_XAI_KEY_PREFIX) and len(key) >= len(_XAI_KEY_PREFIX) + 20
    if connector_type == CONNECTOR_TYPE_GEMINI_APIKEY:
        # Google "AIza…" keys are a fixed 39-char url-safe string.
        return key.startswith(_GEMINI_KEY_PREFIX) and len(key) == _GEMINI_KEY_LENGTH
    return False


# Azure resource/deployment names: letters, digits, hyphen (Azure naming rules).
_AZURE_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
# api-version is a date-ish token, optionally with a -preview suffix.
_AZURE_VERSION_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.")


def _validate_azure_field(name: str, value: str | None, allowed: set[str], max_len: int) -> str:
    if not value:
        raise ValueError(f"{name} is required")
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    if len(value) > max_len:
        raise ValueError(f"{name} must be {max_len} characters or fewer")
    if not all(c in allowed for c in value):
        raise ValueError(f"{name} contains invalid characters")
    return value


def _build_azure_creds(
    *,
    api_key: str | None,
    azure_resource_name: str | None,
    azure_deployment_name: str | None,
    azure_api_version: str | None,
) -> dict[str, Any]:
    """Validate + assemble the Azure OpenAI credential blob.

    All four fields (api_key + the three azure_* config values) are stored in
    the encrypted blob — there are no dedicated DB columns.
    """
    if not api_key or not api_key.strip():
        raise ValueError("api_key is required")
    return {
        "api_key": api_key.strip(),
        "azure_resource_name": _validate_azure_field(
            "azure_resource_name", azure_resource_name, _AZURE_NAME_CHARS, 120
        ),
        "azure_deployment_name": _validate_azure_field(
            "azure_deployment_name", azure_deployment_name, _AZURE_NAME_CHARS, 120
        ),
        "azure_api_version": _validate_azure_field(
            "azure_api_version", azure_api_version, _AZURE_VERSION_CHARS, 40
        ),
    }


def _load_existing_blob(connector: LlmConnector) -> dict[str, Any]:
    """Decode the connector's current credential blob (best-effort).

    Returns an empty dict when the blob is missing or malformed so callers can
    treat absent values as "no prior value" during partial rotation.
    """
    raw = connector.credentials or ""
    try:
        blob = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return blob if isinstance(blob, dict) else {}


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
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_region: str | None = None,
    aws_model_id: str | None = None,
    azure_resource_name: str | None = None,
    azure_deployment_name: str | None = None,
    azure_api_version: str | None = None,
) -> LlmConnector:
    """Rotate the credential blob in-place. Caller commits."""
    blob: dict[str, Any]
    if connector.connector_type in _APIKEY_CONNECTOR_TYPES:
        blob = _validate_api_key_blob(
            connector.connector_type, api_key, required_msg="api_key is required for rotation"
        )
    elif connector.connector_type == CONNECTOR_TYPE_OPENAI_COMPATIBLE:
        if not base_url:
            raise ValueError("base_url is required for rotation")
        try:
            base_url = validate_compatible_base_url(base_url)
        except InvalidBaseUrlError as exc:
            raise ValueError(str(exc)) from exc
        blob = {"base_url": base_url, "bearer": bearer or None}
        connector.base_url_plain = base_url
    elif connector.connector_type == CONNECTOR_TYPE_BEDROCK:
        # Partial rotation: keep existing fields when a new value isn't supplied.
        existing: dict[str, Any] = {}
        try:
            parsed = json.loads(connector.credentials or "{}")
            if isinstance(parsed, dict):
                existing = parsed
        except (json.JSONDecodeError, TypeError):
            existing = {}
        blob = _build_bedrock_creds(
            aws_access_key_id=aws_access_key_id or existing.get("aws_access_key_id"),
            aws_secret_access_key=(aws_secret_access_key or existing.get("aws_secret_access_key")),
            aws_region=aws_region or existing.get("aws_region"),
            aws_model_id=aws_model_id or existing.get("aws_model_id"),
        )
    elif connector.connector_type == CONNECTOR_TYPE_AZURE_OPENAI:
        # Partial rotation: any omitted field keeps its current value, so an
        # admin can swap just the resource/deployment/version (or just the key)
        # without recreating the connector.
        # Only None means "field omitted, keep current value". An explicit ""
        # is passed through to _build_azure_creds() so it is rejected rather
        # than silently preserving the old value.
        current = _load_existing_blob(connector)
        new_api_key = current.get("api_key") if api_key is None else api_key.strip()
        blob = _build_azure_creds(
            api_key=new_api_key,
            azure_resource_name=(
                current.get("azure_resource_name")
                if azure_resource_name is None
                else azure_resource_name
            ),
            azure_deployment_name=(
                current.get("azure_deployment_name")
                if azure_deployment_name is None
                else azure_deployment_name
            ),
            azure_api_version=(
                current.get("azure_api_version") if azure_api_version is None else azure_api_version
            ),
        )
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
        connector.model_hint = _normalise_model_hint(
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


def purge_call_log_older_than(db: Session, *, retention_days: int) -> int:
    """Delete llm_call_log rows older than ``retention_days``.

    Returns the number of rows deleted. The caller owns the transaction
    (commits). ``retention_days`` is supplied by the caller (which reads it
    from system settings each run) so the retention window stays configurable
    without a hardcoded constant.
    """
    from datetime import timedelta

    from app.core.time import utcnow

    # Fail closed on out-of-bounds windows. A non-positive value would push the
    # cutoff to now/future and delete nearly all history; an oversized value is
    # equally suspect. The admin UI/schema clamp to 7-365, so a value outside
    # that range means a corrupt or tampered persisted setting — refuse rather
    # than over-delete. The daily cleanup loop catches this and retries next pass.
    if not 7 <= retention_days <= 365:
        raise ValueError("retention_days must be between 7 and 365")

    cutoff = utcnow() - timedelta(days=retention_days)
    result = db.execute(delete(LlmCallLog).where(LlmCallLog.created_at < cutoff))
    return result.rowcount or 0


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


def _calendar_month_start() -> datetime:
    """First instant (UTC, naive) of the current calendar month."""
    from app.core.time import utcnow

    now = utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def current_month_token_usage(db: Session, connector_id: int) -> int:
    """Sum tokens_in + tokens_out for ``connector_id`` in the current month.

    Direct aggregation against the indexed ``llm_call_log.created_at`` column.
    NULL token counts are coalesced to 0. Returns 0 when there are no rows.
    Used by the gateway pre-flight cap check + the admin usage-vs-cap display
    (issue #339).
    """
    month_start = _calendar_month_start()
    total = db.execute(
        select(
            func.coalesce(func.sum(LlmCallLog.tokens_in), 0)
            + func.coalesce(func.sum(LlmCallLog.tokens_out), 0)
        ).where(
            LlmCallLog.connector_id == connector_id,
            LlmCallLog.created_at >= month_start,
        )
    ).scalar_one()
    return int(total or 0)


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
    "CreateConnectorPayload",
    "audit_event",
    "build_create_payload",
    "create_connector",
    "current_month_token_usage",
    "delete_connector",
    "get_connector",
    "get_connector_for_user",
    "get_usage_stats",
    "get_user_label",
    "list_all_connectors",
    "list_connectors_for_user",
    "log_call",
    "purge_call_log_older_than",
    "revoke_connector",
    "rotate_credentials",
    "set_default_for_user",
    "set_monthly_cap",
    "unset_default_for_user",
    "update_metadata",
]
