"""Add tidal_collection_playlist_id to events.

Revision ID: 043
Revises: 042
Create Date: 2026-05-11
"""

import sqlalchemy as sa

from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("tidal_collection_playlist_id", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("events", "tidal_collection_playlist_id")
