"""Org-scoped LLM connector + llm_enabled rescope cleanup.

Revision ID: 056
Revises: 055
Create Date: 2026-06-09

- llm_connectors.scope ('user'|'org'), user_id nullable, CHECK org<->NULL user
  + CHECK scope limited to ('user','org')
- llm_audit_event.actor_user_id nullable (system-context calls)
- system_settings.llm_model dropped (display-only legacy)
- Backfill: if llm_default_connector_id points at the migration-047-seeded
  env-var connector ("Org Default (migrated from env var)"), convert that row
  to scope='org' (it was the house key). Any other user-scoped default is
  cleared — an admin must create a proper org connector.
- Downgrade preserves the org credential by reattaching org rows to the first
  admin (scope='user'); rows are deleted only when no admin exists. NULL-actor
  audit rows cannot survive the restored NOT NULL and are purged.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "056"
down_revision: str | None = "055"
branch_labels = None
depends_on = None

_MIGRATED_DISPLAY_NAME = "Org Default (migrated from env var)"


def upgrade() -> None:
    op.add_column(
        "llm_connectors",
        sa.Column("scope", sa.String(10), nullable=False, server_default="user"),
    )
    op.alter_column("llm_connectors", "user_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("llm_audit_event", "actor_user_id", existing_type=sa.Integer(), nullable=True)
    op.drop_column("system_settings", "llm_model")

    # Backfill BEFORE adding the CHECK so the converted row satisfies it.
    conn = op.get_bind()
    default_id = conn.execute(
        sa.text("SELECT llm_default_connector_id FROM system_settings LIMIT 1")
    ).scalar()
    if default_id is not None:
        row = conn.execute(
            sa.text("SELECT id, display_name FROM llm_connectors WHERE id = :cid"),
            {"cid": default_id},
        ).first()
        if row is not None and row[1] == _MIGRATED_DISPLAY_NAME:
            conn.execute(
                sa.text(
                    "UPDATE llm_connectors "
                    "SET scope = 'org', user_id = NULL, is_default = false "
                    "WHERE id = :cid"
                ),
                {"cid": default_id},
            )
        elif row is not None:
            conn.execute(sa.text("UPDATE system_settings SET llm_default_connector_id = NULL"))

    op.create_check_constraint(
        "ck_llm_connectors_scope_valid",
        "llm_connectors",
        "scope IN ('user', 'org')",
    )
    op.create_check_constraint(
        "ck_llm_connectors_org_scope_no_user",
        "llm_connectors",
        "(scope = 'org') = (user_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_llm_connectors_org_scope_no_user", "llm_connectors", type_="check")
    op.drop_constraint("ck_llm_connectors_scope_valid", "llm_connectors", type_="check")
    # Org rows cannot survive a NOT NULL user_id. Preserve the credential by
    # reattaching them to the first admin (mirrors the upgrade backfill); only
    # when no admin exists do we clear the default pointer and delete them.
    conn = op.get_bind()
    admin_id = conn.execute(
        sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1")
    ).scalar()
    if admin_id is not None:
        conn.execute(
            sa.text("UPDATE llm_connectors SET scope = 'user', user_id = :uid WHERE scope = 'org'"),
            {"uid": admin_id},
        )
    else:
        conn.execute(
            sa.text(
                "UPDATE system_settings SET llm_default_connector_id = NULL "
                "WHERE llm_default_connector_id IN "
                "(SELECT id FROM llm_connectors WHERE scope = 'org')"
            )
        )
        conn.execute(sa.text("DELETE FROM llm_connectors WHERE scope = 'org'"))
    op.add_column(
        "system_settings",
        sa.Column(
            "llm_model",
            sa.String(100),
            nullable=False,
            server_default="claude-haiku-4-5-20251001",
        ),
    )
    # System-context audit rows cannot survive the NOT NULL schema.
    conn.execute(sa.text("DELETE FROM llm_audit_event WHERE actor_user_id IS NULL"))
    op.alter_column("llm_audit_event", "actor_user_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("llm_connectors", "user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("llm_connectors", "scope")
