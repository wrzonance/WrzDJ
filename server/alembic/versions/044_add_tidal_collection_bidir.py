"""Add tidal_collection_track_id to requests and tidal_collection_bidirectional to events.

Revision ID: 044
Revises: 043
Create Date: 2026-05-11
"""

import sqlalchemy as sa

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requests",
        sa.Column("tidal_collection_track_id", sa.String(50), nullable=True),
    )
    op.create_index(
        "ix_requests_tidal_collection_track_id",
        "requests",
        ["tidal_collection_track_id"],
        unique=False,
    )
    op.add_column(
        "events",
        sa.Column(
            "tidal_collection_bidirectional",
            sa.Boolean,
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_requests_tidal_collection_track_id", table_name="requests", if_exists=True)
    op.drop_column("requests", "tidal_collection_track_id")
    op.drop_column("events", "tidal_collection_bidirectional")
