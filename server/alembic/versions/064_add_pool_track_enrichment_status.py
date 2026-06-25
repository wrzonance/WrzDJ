"""Add pool-track enrichment status.

Revision ID: 064
Revises: 063
Create Date: 2026-06-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "064"
down_revision: str | None = "063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "set_pool_tracks",
        sa.Column(
            "enrichment_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    # Mirror pool._has_provider_gap: a track is only "enriched" when every
    # provider-fillable contract field (bpm/key/genre/duration_sec) is present.
    # A weaker OR heuristic would mark partially-filled rows enriched, so the
    # background worker (which only processes "pending") could never complete
    # them — they'd be stuck looking enriched while a fresh import flags pending.
    op.execute(
        """
        UPDATE set_pool_tracks
        SET enrichment_status = CASE
            WHEN bpm IS NOT NULL
                 AND "key" IS NOT NULL
                 AND genre IS NOT NULL
                 AND duration_sec IS NOT NULL
            THEN 'enriched'
            ELSE 'pending'
        END
        """
    )


def downgrade() -> None:
    op.drop_column("set_pool_tracks", "enrichment_status")
