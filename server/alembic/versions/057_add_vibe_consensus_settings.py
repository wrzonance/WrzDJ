"""Vibe consensus threshold settings (issue #391).

Revision ID: 057
Revises: 056
Create Date: 2026-06-10

Community consensus over track_vibe_overrides is gated on
sample_size >= vibe_consensus_min_sample AND energy stddev <
vibe_consensus_max_stddev. Both admin-tunable via PATCH /api/admin/settings.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "057"
down_revision: str | None = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "vibe_consensus_min_sample", sa.Integer(), nullable=False, server_default=sa.text("3")
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "vibe_consensus_max_stddev", sa.Float(), nullable=False, server_default=sa.text("1.5")
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "vibe_consensus_max_stddev")
    op.drop_column("system_settings", "vibe_consensus_min_sample")
