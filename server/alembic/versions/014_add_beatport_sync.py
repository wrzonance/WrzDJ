"""Add Beatport sync columns

User: beatport_access_token, beatport_refresh_token, beatport_token_expires_at
Event: beatport_sync_enabled

Revision ID: 014
Revises: 013
Create Date: 2026-02-12 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("beatport_access_token", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("beatport_refresh_token", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("beatport_token_expires_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("beatport_oauth_state", sa.String(64), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "beatport_sync_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("events", "beatport_sync_enabled")
    op.drop_column("users", "beatport_oauth_state")
    op.drop_column("users", "beatport_token_expires_at")
    op.drop_column("users", "beatport_refresh_token")
    op.drop_column("users", "beatport_access_token")
