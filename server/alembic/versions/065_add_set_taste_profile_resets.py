"""Add SetBuilder taste-profile reset markers (issue #409).

Revision ID: 065
Revises: 064
Create Date: 2026-06-26

Profiles are computed at read time from TrackVibeOverride history. Resetting a
profile stores a marker instead of deleting override rows.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "065"
down_revision: str | None = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "set_taste_profile_resets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "reset_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_set_taste_profile_resets_user_id",
        "set_taste_profile_resets",
        ["user_id"],
    )
    op.create_index(
        "ix_set_taste_profile_resets_user_reset_at",
        "set_taste_profile_resets",
        ["user_id", "reset_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_set_taste_profile_resets_user_reset_at",
        table_name="set_taste_profile_resets",
    )
    op.drop_index("ix_set_taste_profile_resets_user_id", table_name="set_taste_profile_resets")
    op.drop_table("set_taste_profile_resets")
