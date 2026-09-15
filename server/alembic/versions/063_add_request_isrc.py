"""Add isrc to requests (#552) — carry the search-result ISRC from submit.

Search (Tidal/Beatport/Spotify) already returns an ISRC; capturing it on the
Request lets enrichment use it as the ISRC-first cache key + master-store
identity, instead of re-deriving it during the background cascade.

Revision ID: 063
Revises: 062
Create Date: 2026-06-24
"""

import sqlalchemy as sa

from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("isrc", sa.String(length=15), nullable=True))


def downgrade() -> None:
    op.drop_column("requests", "isrc")
