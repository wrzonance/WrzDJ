"""Add banner_filename and banner_colors to events table

Revision ID: 009
Revises: 008
Create Date: 2026-02-08 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("banner_filename", sa.String(255), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("banner_colors", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "banner_colors")
    op.drop_column("events", "banner_filename")
