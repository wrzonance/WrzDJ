"""Add WrzDJSet transition overlap setting (issue #394).

Revision ID: 059
Revises: 058
Create Date: 2026-06-13

Average transition overlap is a per-set planning input. It shrinks effective
playtime as tracks blend: total - (slots - 1) * overlap.
"""

import sqlalchemy as sa

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sets",
        sa.Column(
            "avg_transition_overlap_sec",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("8"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sets", "avg_transition_overlap_sec")
