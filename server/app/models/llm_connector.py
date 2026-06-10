"""LLM connector models — provider-agnostic credential storage and audit trail.

Tables:
- llm_connectors: per-DJ LLM provider credentials (encrypted at rest)
- llm_call_log: per-call telemetry (counts only — no prompt/completion content)
- llm_audit_event: security-relevant credential lifecycle events

See docs/superpowers/specs/2026-05-24-admin-ai-oauth-design.md §4.2.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedText
from app.models.base import Base

# Valid connector types — keep in sync with services/llm/registry.py
CONNECTOR_TYPE_OPENAI_APIKEY = "openai_apikey"
CONNECTOR_TYPE_ANTHROPIC_APIKEY = "anthropic_apikey"
CONNECTOR_TYPE_OPENAI_COMPATIBLE = "openai_compatible"
CONNECTOR_TYPE_GEMINI_APIKEY = "gemini_apikey"
CONNECTOR_TYPE_AZURE_OPENAI = "azure_openai"
CONNECTOR_TYPE_BEDROCK = "bedrock"
CONNECTOR_TYPE_OPENROUTER_APIKEY = "openrouter_apikey"
CONNECTOR_TYPE_XAI_APIKEY = "xai_apikey"

VALID_CONNECTOR_TYPES = frozenset(
    {
        CONNECTOR_TYPE_OPENAI_APIKEY,
        CONNECTOR_TYPE_ANTHROPIC_APIKEY,
        CONNECTOR_TYPE_OPENAI_COMPATIBLE,
        CONNECTOR_TYPE_GEMINI_APIKEY,
        CONNECTOR_TYPE_AZURE_OPENAI,
        CONNECTOR_TYPE_BEDROCK,
        CONNECTOR_TYPE_OPENROUTER_APIKEY,
        CONNECTOR_TYPE_XAI_APIKEY,
    }
)

# Connector statuses
STATUS_ACTIVE = "active"
STATUS_AUTH_INVALID = "auth_invalid"
STATUS_DISABLED = "disabled"

# Connector scope — 'user' rows belong to a DJ; 'org' rows belong to the
# organization itself (house-billed fallback). Org rows have user_id NULL,
# enforced by ck_llm_connectors_org_scope_no_user below.
SCOPE_USER = "user"
SCOPE_ORG = "org"

# Health-check status values written to ``last_health_check_status``. Kept here
# so the API/background loop/admin UI all use the same vocabulary. These are
# *outcomes*, not connector statuses — a single connector accumulates many
# health-check rows over its lifetime; only the most recent outcome is stored
# on the row itself (audit_event rows preserve the full history).
HEALTH_CHECK_OK = "ok"
HEALTH_CHECK_AUTH_INVALID = "auth_invalid"
HEALTH_CHECK_RATE_LIMITED = "rate_limited"
HEALTH_CHECK_QUOTA_EXCEEDED = "quota_exceeded"
HEALTH_CHECK_PROVIDER_UNAVAILABLE = "provider_unavailable"
HEALTH_CHECK_ERROR = "error"

VALID_HEALTH_CHECK_STATUSES = frozenset(
    {
        HEALTH_CHECK_OK,
        HEALTH_CHECK_AUTH_INVALID,
        HEALTH_CHECK_RATE_LIMITED,
        HEALTH_CHECK_QUOTA_EXCEEDED,
        HEALTH_CHECK_PROVIDER_UNAVAILABLE,
        HEALTH_CHECK_ERROR,
    }
)

# Audit event types
AUDIT_CREATED = "connector_created"
AUDIT_CREDENTIALS_ROTATED = "connector_credentials_rotated"
AUDIT_DELETED = "connector_deleted"
AUDIT_REVOKED_BY_ADMIN = "connector_revoked_by_admin"
AUDIT_AUTH_INVALID_OBSERVED = "auth_invalid_observed"
AUDIT_POLICY_CHANGED = "policy_changed"
AUDIT_HEALTH_CHECK = "connector_health_check"
AUDIT_DEFAULT_SET = "connector_default_set"
AUDIT_DEFAULT_UNSET = "connector_default_unset"
# Emitted by the background monitor when a periodic health check flips a
# previously-active connector into ``auth_invalid``. Distinct from
# ``AUDIT_HEALTH_CHECK`` (which is fired on EVERY check, OK or not) so admins
# can filter to the credential-lifecycle subset.
AUDIT_HEALTH_CHECK_FAILED = "connector_health_check_failed"


class LlmConnector(Base):
    """Per-DJ LLM provider credentials.

    `credentials` is a JSON string encrypted via Fernet. Shape varies by type:
    - openai_apikey / anthropic_apikey / openrouter_apikey: {"api_key": "..."}
    - openai_compatible: {"base_url": "...", "bearer": "..." | null}
    - azure_openai: {"api_key": "...", "azure_resource_name": "...",
      "azure_deployment_name": "...", "azure_api_version": "..."}
    - bedrock: {"aws_access_key_id": "...", "aws_secret_access_key": "...",
      "aws_region": "...", "aws_model_id": "..."}

    `base_url_plain` mirrors the openai_compatible base_url in plaintext so admin
    listing can render without decrypting. Contains no credentials.
    """

    __tablename__ = "llm_connectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    connector_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(
        String(10), nullable=False, default=SCOPE_USER, server_default=text("'user'")
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_ACTIVE, server_default=STATUS_ACTIVE
    )
    credentials: Mapped[str] = mapped_column(EncryptedText, nullable=False)

    base_url_plain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_hint: Mapped[str | None] = mapped_column(String(80), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Per-DJ explicit default. At most one connector per user_id may have
    # is_default=True — enforced at the DB layer via a partial unique index
    # (Postgres) and at the service layer via clear-then-set semantics. When
    # set, the gateway prefers this connector over the MRU heuristic. See
    # issue #336.
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    # Health-check observability (issue #346 + #340).
    # ``last_health_check_at`` is written by every health-check invocation —
    # the DJ-triggered Test button AND the background monitor. ``last_health_check_status``
    # records the outcome (see HEALTH_CHECK_* constants).
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_health_check_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Admin-set monthly token cap (issue #339). NULL = unlimited. When set, the
    # gateway refuses dispatch once the current calendar month's summed
    # tokens_in + tokens_out for this connector meets or exceeds the cap. The
    # cap is admin-only (set via /api/admin/llm/connectors/{id}/cap) and is
    # checked PRE-FLIGHT only — editing it never disrupts an in-flight call.
    monthly_token_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "connector_type", "display_name", name="uq_dj_connector_label"),
        # A negative cap would make the connector permanently "over budget". The
        # API schema (ge=0) and service layer already reject negatives; this DB
        # CHECK is the defence-in-depth backstop so a bad write can never persist.
        CheckConstraint(
            "monthly_token_cap IS NULL OR monthly_token_cap >= 0",
            name="ck_llm_connectors_monthly_token_cap_nonnegative",
        ),
        # Org rows must have no owner; user rows must have one.
        CheckConstraint(
            "(scope = 'org') = (user_id IS NULL)",
            name="ck_llm_connectors_org_scope_no_user",
        ),
        Index("ix_user_active", "user_id", "status"),
        # Partial unique index — only enforced on Postgres. SQLite ignores
        # the postgresql_where clause but still creates an unfiltered index;
        # since the service layer clears siblings before flipping a row to
        # True, that is harmless. The migration uses the same clause so the
        # CI ``alembic check`` step stays clean on Postgres.
        Index(
            "ix_llm_connectors_user_default_unique",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default"),
        ),
    )


class LlmCallLog(Base):
    """Per-call telemetry — counts only, never prompt/completion content.

    30-day retention is the default; daily cleanup deletes older rows.
    """

    __tablename__ = "llm_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_id: Mapped[int] = mapped_column(
        ForeignKey("llm_connectors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )


class LlmAuditEvent(Base):
    """Security-relevant connector lifecycle events.

    Indefinite retention (no auto-cleanup). Includes admin-triggered events
    so org operators have a complete audit trail for security reviews.
    """

    __tablename__ = "llm_audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL actor = system-context call (no DJ actor); see gateway dispatch.
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    target_connector_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_connectors.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
