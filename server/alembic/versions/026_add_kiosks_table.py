"""Add kiosks table for kiosk pairing

Revision ID: 026
Revises: 025
Create Date: 2026-02-20 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kiosks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pair_code", sa.String(6), nullable=False),
        sa.Column("session_token", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("event_code", sa.String(10), nullable=True),
        sa.Column(
            "paired_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pairing"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("paired_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("pair_expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_kiosks_pair_code", "kiosks", ["pair_code"], unique=True)
    op.create_index("ix_kiosks_session_token", "kiosks", ["session_token"], unique=True)
    op.create_index("ix_kiosks_event_code", "kiosks", ["event_code"])


def downgrade() -> None:
    op.drop_index("ix_kiosks_event_code")
    op.drop_index("ix_kiosks_session_token")
    op.drop_index("ix_kiosks_pair_code")
    op.drop_table("kiosks")
