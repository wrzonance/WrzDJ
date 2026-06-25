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
    # Backfill terminal statuses only — there is no background worker at migration
    # time, so a legacy row must never be left "pending" (it would report
    # in_progress forever and make clients poll with nothing to clear it).
    # Mirror pool._has_provider_gap: rows with the full contract (bpm/key/genre/
    # duration_sec) are "enriched"; anything partial is "failed" — exactly what
    # the runtime worker now records when a pass can't close the gap. Legacy rows
    # re-enrich on their next import/recompute touch.
    op.execute(
        """
        UPDATE set_pool_tracks
        SET enrichment_status = CASE
            WHEN bpm IS NOT NULL
                 AND "key" IS NOT NULL
                 AND genre IS NOT NULL
                 AND duration_sec IS NOT NULL
            THEN 'enriched'
            ELSE 'failed'
        END
        """
    )


def downgrade() -> None:
    op.drop_column("set_pool_tracks", "enrichment_status")
