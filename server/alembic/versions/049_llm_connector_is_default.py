"""Per-DJ explicit default connector toggle (issue #336).

Revision ID: 049
Revises: 048
Create Date: 2026-05-28

Adds llm_connectors.is_default (bool, NOT NULL, default false) plus a partial
unique index enforcing at most one default per user. Backfills by marking each
DJ's MRU active connector as default on first deploy so resolution behavior is
unchanged for existing users (they keep getting their previous most-recently
used connector — now pinned).
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from alembic import op

revision: str = "049"
down_revision: str | None = "048"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    op.add_column(
        "llm_connectors",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    bind = op.get_bind()
    dialect = bind.dialect.name

    # Partial unique index: at most one default per user_id. Both Postgres and
    # SQLite (3.8+) support the partial-index WHERE clause; other dialects skip
    # the index — the service layer still enforces single-default semantics.
    if dialect == "postgresql":
        op.create_index(
            "ix_llm_connectors_user_default_unique",
            "llm_connectors",
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("is_default"),
        )
    elif dialect == "sqlite":
        op.create_index(
            "ix_llm_connectors_user_default_unique",
            "llm_connectors",
            ["user_id"],
            unique=True,
            sqlite_where=sa.text("is_default"),
        )
    else:  # pragma: no cover — production runs Postgres; SQLite is tests
        # Fall back to a non-unique covering index so resolver lookups stay
        # cheap. The service layer (clear-then-set) still enforces uniqueness.
        op.create_index(
            "ix_llm_connectors_user_default_unique",
            "llm_connectors",
            ["user_id"],
        )

    _backfill_mru_defaults(bind)


def downgrade() -> None:
    op.drop_index("ix_llm_connectors_user_default_unique", table_name="llm_connectors")
    op.drop_column("llm_connectors", "is_default")


def _backfill_mru_defaults(bind: sa.engine.Connection) -> None:
    """Mark each user's MRU active connector as default (one per user).

    MRU = ``last_used_at`` DESC NULLS LAST, ``id`` DESC — same ordering the
    gateway resolver uses. Skips users that have no active connector. Idempotent
    on re-run: if a user already has any default, leaves it alone.
    """
    user_rows = bind.execute(
        sa.text("SELECT DISTINCT user_id FROM llm_connectors WHERE status = 'active'")
    ).all()

    for (user_id,) in user_rows:
        existing_default = bind.execute(
            sa.text(
                "SELECT id FROM llm_connectors "
                "WHERE user_id = :uid AND is_default = :truthy AND status = 'active' "
                "LIMIT 1"
            ),
            {"uid": user_id, "truthy": True},
        ).first()
        if existing_default is not None:
            continue

        # ORDER BY last_used_at DESC NULLS LAST is portable via the CASE trick
        # so the migration works on both Postgres and SQLite (the latter's
        # NULLS handling differs by default).
        mru = bind.execute(
            sa.text(
                "SELECT id FROM llm_connectors "
                "WHERE user_id = :uid AND status = 'active' "
                "ORDER BY CASE WHEN last_used_at IS NULL THEN 1 ELSE 0 END, "
                "last_used_at DESC, id DESC "
                "LIMIT 1"
            ),
            {"uid": user_id},
        ).first()
        if mru is None:
            continue

        bind.execute(
            sa.text("UPDATE llm_connectors SET is_default = :truthy WHERE id = :cid"),
            {"truthy": True, "cid": mru[0]},
        )
        logger.info(
            "048_llm_connector_is_default: backfilled is_default=True for "
            "connector_id=%s user_id=%s",
            mru[0],
            user_id,
        )
