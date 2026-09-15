"""Add now_playing visibility fields

Revision ID: 004
Revises: 003
Create Date: 2026-02-05 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "5bb46508476b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "now_playing",
        sa.Column("manual_hide_now_playing", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "now_playing",
        sa.Column("last_shown_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("now_playing", "last_shown_at")
    op.drop_column("now_playing", "manual_hide_now_playing")
