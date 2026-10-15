"""Store Apple Music playlist exports on WrzDJSet sets.

Revision ID: 072
Revises: 071
"""

import sqlalchemy as sa

from alembic import op

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sets", sa.Column("apple_music_playlist_id", sa.String(length=100)))
    op.add_column(
        "sets",
        sa.Column(
            "apple_music_export_pending",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("sets", "apple_music_export_pending")
    op.drop_column("sets", "apple_music_playlist_id")
