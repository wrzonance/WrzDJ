"""LLM connector models — provider-agnostic credential storage and audit trail.

Tables:
- llm_connectors: per-DJ LLM provider credentials (encrypted at rest)
- llm_call_log: per-call telemetry (counts only — no prompt/completion content)
- llm_audit_event: security-relevant credential lifecycle events

See docs/superpowers/specs/2026-05-24-admin-ai-oauth-design.md §4.2.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedText
from app.models.base import Base

# Valid connector types — keep in sync with services/llm/registry.py
CONNECTOR_TYPE_OPENAI_APIKEY = "openai_apikey"
CONNECTOR_TYPE_ANTHROPIC_APIKEY = "anthropic_apikey"
CONNECTOR_TYPE_OPENAI_COMPATIBLE = "openai_compatible"
CONNECTOR_TYPE_AZURE_OPENAI = "azure_openai"
CONNECTOR_TYPE_BEDROCK = "bedrock"
CONNECTOR_TYPE_OPENROUTER_APIKEY = "openrouter_apikey"
CONNECTOR_TYPE_XAI_APIKEY = "xai_apikey"

VALID_CONNECTOR_TYPES = frozenset(
    {
        CONNECTOR_TYPE_OPENAI_APIKEY,
        CONNECTOR_TYPE_ANTHROPIC_APIKEY,
        CONNECTOR_TYPE_OPENAI_COMPATIBLE,
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

# Audit event types
AUDIT_CREATED = "connector_created"
AUDIT_CREDENTIALS_ROTATED = "connector_credentials_rotated"
AUDIT_DELETED = "connector_deleted"
AUDIT_REVOKED_BY_ADMIN = "connector_revoked_by_admin"
AUDIT_AUTH_INVALID_OBSERVED = "auth_invalid_observed"
AUDIT_POLICY_CHANGED = "policy_changed"
AUDIT_HEALTH_CHECK = "connector_health_check"


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
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connector_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_ACTIVE)
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

    __table_args__ = (
        UniqueConstraint("user_id", "connector_type", "display_name", name="uq_dj_connector_label"),
        Index("ix_user_active", "user_id", "status"),
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
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    target_connector_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_connectors.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
