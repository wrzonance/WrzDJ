"""Track Apple Music exports that need explicit user reconciliation.

Revision ID: 073
Revises: 072
"""

import sqlalchemy as sa

from alembic import op

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sets",
        sa.Column(
            "apple_music_export_uncertain",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE sets SET apple_music_export_uncertain = true "
        "WHERE apple_music_export_pending = true"
    )


def downgrade() -> None:
    op.drop_column("sets", "apple_music_export_uncertain")
