"""Add pending_email_changes table for self-service email verification.

Revision ID: 042
Revises: 8addb2680814
Create Date: 2026-05-08
"""

import sqlalchemy as sa

from alembic import op

revision = "042"
down_revision = "8addb2680814"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_email_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("new_email", sa.String(255), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_email_changes_user_id", "pending_email_changes", ["user_id"])
    op.create_index(
        "ix_pending_email_changes_token",
        "pending_email_changes",
        ["token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_pending_email_changes_token", table_name="pending_email_changes")
    op.drop_index("ix_pending_email_changes_user_id", table_name="pending_email_changes")
    op.drop_table("pending_email_changes")
