"""LLM gateway: connectors + call log + audit event + system_settings columns + data migration.

Revision ID: 046
Revises: a11334c031bb
Create Date: 2026-05-24

Creates:
- llm_connectors: per-DJ encrypted credential storage (Fernet via EncryptedText)
- llm_call_log: per-call telemetry (counts only, no prompt/completion content)
- llm_audit_event: connector lifecycle events for security review
- 3 new columns on system_settings (apikey policy, compatible policy, default connector FK)

Data migration:
- If ANTHROPIC_API_KEY env var is set, creates an "anthropic_apikey" connector
  named "Org Default (migrated from env var)" owned by the first admin user,
  and points system_settings.llm_default_connector_id at it.
- Idempotent: skips if a connector with that name already exists.
- Skipped silently if no env var, no admin user, or encryption key unavailable.
"""

import json
import logging
import os
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import op
from app.core.encryption import encrypt_value

revision: str = "046"
down_revision: str | None = "a11334c031bb"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)

_MIGRATED_DISPLAY_NAME = "Org Default (migrated from env var)"


def upgrade() -> None:
    # llm_connectors
    op.create_table(
        "llm_connectors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("connector_type", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("credentials", sa.Text(), nullable=False),
        sa.Column("base_url_plain", sa.String(255), nullable=True),
        sa.Column("model_hint", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.UniqueConstraint(
            "user_id", "connector_type", "display_name", name="uq_dj_connector_label"
        ),
    )
    op.create_index("ix_llm_connectors_user_id", "llm_connectors", ["user_id"])
    op.create_index("ix_llm_connectors_connector_type", "llm_connectors", ["connector_type"])
    op.create_index("ix_user_active", "llm_connectors", ["user_id", "status"])

    # llm_call_log
    op.create_table(
        "llm_call_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connector_id",
            sa.Integer(),
            sa.ForeignKey("llm_connectors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_llm_call_log_connector_id", "llm_call_log", ["connector_id"])
    op.create_index("ix_llm_call_log_purpose", "llm_call_log", ["purpose"])
    op.create_index("ix_llm_call_log_created_at", "llm_call_log", ["created_at"])

    # llm_audit_event
    op.create_table(
        "llm_audit_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "target_connector_id",
            sa.Integer(),
            sa.ForeignKey("llm_connectors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_llm_audit_event_actor_user_id", "llm_audit_event", ["actor_user_id"])
    op.create_index("ix_llm_audit_event_event_type", "llm_audit_event", ["event_type"])

    # system_settings additions
    op.add_column(
        "system_settings",
        sa.Column(
            "llm_apikey_connectors_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "llm_compatible_connector_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "llm_default_connector_id",
            sa.Integer(),
            sa.ForeignKey("llm_connectors.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Data migration: convert ANTHROPIC_API_KEY env var into a connector + org default
    _migrate_env_var_anthropic_key()


def downgrade() -> None:
    op.drop_column("system_settings", "llm_default_connector_id")
    op.drop_column("system_settings", "llm_compatible_connector_enabled")
    op.drop_column("system_settings", "llm_apikey_connectors_enabled")

    op.drop_index("ix_llm_audit_event_event_type", table_name="llm_audit_event")
    op.drop_index("ix_llm_audit_event_actor_user_id", table_name="llm_audit_event")
    op.drop_table("llm_audit_event")

    op.drop_index("ix_llm_call_log_created_at", table_name="llm_call_log")
    op.drop_index("ix_llm_call_log_purpose", table_name="llm_call_log")
    op.drop_index("ix_llm_call_log_connector_id", table_name="llm_call_log")
    op.drop_table("llm_call_log")

    op.drop_index("ix_user_active", table_name="llm_connectors")
    op.drop_index("ix_llm_connectors_connector_type", table_name="llm_connectors")
    op.drop_index("ix_llm_connectors_user_id", table_name="llm_connectors")
    op.drop_table("llm_connectors")


def _migrate_env_var_anthropic_key() -> None:
    """Best-effort data migration. Never fails the migration."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return

    conn = op.get_bind()
    session = Session(bind=conn)
    try:
        admin_row = session.execute(
            sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1")
        ).first()
        if not admin_row:
            logger.info("046_admin_ai_oauth: no admin user found, skipping data migration")
            return

        admin_id = admin_row[0]

        # Idempotency: skip if a connector with this label already exists.
        existing = session.execute(
            sa.text("SELECT id FROM llm_connectors WHERE user_id = :uid AND display_name = :name"),
            {"uid": admin_id, "name": _MIGRATED_DISPLAY_NAME},
        ).first()
        if existing:
            logger.info("046_admin_ai_oauth: connector already exists, skipping data migration")
            return

        try:
            encrypted_creds = encrypt_value(json.dumps({"api_key": api_key}))
        except Exception:
            logger.warning("046_admin_ai_oauth: encryption unavailable, skipping data migration")
            return

        # Pull anthropic_model from settings if available; falls back to default.
        try:
            from app.core.config import get_settings

            model_hint = get_settings().anthropic_model
        except Exception:
            model_hint = "claude-haiku-4-5-20251001"

        now = datetime.now(UTC).replace(tzinfo=None)
        result = session.execute(
            sa.text(
                "INSERT INTO llm_connectors "
                "(user_id, connector_type, display_name, status, credentials, "
                "model_hint, created_at, updated_at) "
                "VALUES (:uid, :ctype, :name, :status, :creds, "
                ":mhint, :created, :updated) "
                "RETURNING id"
            ),
            {
                "uid": admin_id,
                "ctype": "anthropic_apikey",
                "name": _MIGRATED_DISPLAY_NAME,
                "status": "active",
                "creds": encrypted_creds,
                "mhint": model_hint,
                "created": now,
                "updated": now,
            },
        )
        connector_id_row = result.first()
        if connector_id_row is None:
            # SQLite doesn't support RETURNING — fetch lastrowid via execute
            connector_id = session.execute(
                sa.text(
                    "SELECT id FROM llm_connectors WHERE user_id = :uid AND display_name = :name"
                ),
                {"uid": admin_id, "name": _MIGRATED_DISPLAY_NAME},
            ).scalar()
        else:
            connector_id = connector_id_row[0]

        if connector_id is None:
            logger.warning("046_admin_ai_oauth: could not resolve new connector id")
            return

        # Ensure system_settings row exists, then point at the new connector.
        ss = session.execute(sa.text("SELECT id FROM system_settings LIMIT 1")).first()
        if ss:
            session.execute(
                sa.text(
                    "UPDATE system_settings SET llm_default_connector_id = :cid WHERE id = :sid"
                ),
                {"cid": connector_id, "sid": ss[0]},
            )
        else:
            session.execute(
                sa.text(
                    "INSERT INTO system_settings (id, llm_default_connector_id) VALUES (1, :cid)"
                ),
                {"cid": connector_id},
            )

        # Audit event
        session.execute(
            sa.text(
                "INSERT INTO llm_audit_event "
                "(actor_user_id, target_connector_id, event_type, created_at) "
                "VALUES (:uid, :cid, :etype, :created)"
            ),
            {
                "uid": admin_id,
                "cid": connector_id,
                "etype": "connector_created",
                "created": now,
            },
        )

        session.commit()
        logger.info(
            "046_admin_ai_oauth: migrated ANTHROPIC_API_KEY env var to "
            "connector_id=%s for admin user_id=%s",
            connector_id,
            admin_id,
        )
    except Exception as exc:
        logger.warning("046_admin_ai_oauth: data migration failed: %s", exc)
        session.rollback()
    finally:
        session.close()
