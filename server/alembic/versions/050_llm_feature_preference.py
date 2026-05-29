"""Add llm_feature_preferences table.

Revision ID: 050
Revises: 049
Create Date: 2026-05-28

Per-feature connector preference (issue #337). Maps ``(user_id, feature)`` to a
pinned ``connector_id`` with a UNIQUE constraint so a DJ has at most one pinned
connector per feature. Both FKs cascade on delete so a deleted user or
connector never leaves a dangling preference.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "050"
down_revision: str | None = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_feature_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("feature", sa.String(length=40), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connector_id"], ["llm_connectors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "feature", name="uq_llm_feature_pref_user_feature"),
    )
    op.create_index(
        "ix_llm_feature_preferences_user_id",
        "llm_feature_preferences",
        ["user_id"],
    )
    op.create_index(
        "ix_llm_feature_preferences_connector_id",
        "llm_feature_preferences",
        ["connector_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_feature_preferences_connector_id", table_name="llm_feature_preferences")
    op.drop_index("ix_llm_feature_preferences_user_id", table_name="llm_feature_preferences")
    op.drop_table("llm_feature_preferences")
