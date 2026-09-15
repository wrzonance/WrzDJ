"""Add kiosk display fields

Revision ID: 002
Revises: 001
Create Date: 2026-02-04 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add now_playing fields to events
    op.add_column(
        "events",
        sa.Column("now_playing_request_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("now_playing_updated_at", sa.DateTime(), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_now_playing_request_id",
        "events",
        "requests",
        ["now_playing_request_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Add artwork_url to requests
    op.add_column(
        "requests",
        sa.Column("artwork_url", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("requests", "artwork_url")
    op.drop_constraint("fk_events_now_playing_request_id", "events", type_="foreignkey")
    op.drop_column("events", "now_playing_updated_at")
    op.drop_column("events", "now_playing_request_id")
