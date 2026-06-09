"""Add WrzDJSet pool tables (set_pool_sources, set_pool_tracks) — issue #388

Revision ID: 053
Revises: 052
Create Date: 2026-06-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "053"
down_revision: str | None = "054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "set_pool_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("external_ref", sa.String(500), nullable=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("meta", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_set_pool_sources_set_id", "set_pool_sources", ["set_id"])

    op.create_table(
        "set_pool_tracks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("set_pool_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("track_id", sa.String(255), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("artist", sa.String(255), nullable=False),
        sa.Column("album", sa.String(255), nullable=True),
        sa.Column("genre", sa.String(100), nullable=True),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("key", sa.String(20), nullable=True),
        sa.Column("camelot", sa.String(3), nullable=True),
        sa.Column("energy", sa.Integer(), nullable=True),
        sa.Column("isrc", sa.String(15), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("artwork_url", sa.String(500), nullable=True),
        sa.Column("dedupe_sig", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("set_id", "dedupe_sig", name="uq_set_pool_track_sig"),
    )
    op.create_index("ix_set_pool_tracks_set_id", "set_pool_tracks", ["set_id"])
    op.create_index("ix_set_pool_tracks_source_id", "set_pool_tracks", ["source_id"])
    op.create_index("ix_set_pool_tracks_dedupe_sig", "set_pool_tracks", ["dedupe_sig"])


def downgrade() -> None:
    op.drop_index("ix_set_pool_tracks_dedupe_sig", table_name="set_pool_tracks")
    op.drop_index("ix_set_pool_tracks_source_id", table_name="set_pool_tracks")
    op.drop_index("ix_set_pool_tracks_set_id", table_name="set_pool_tracks")
    op.drop_table("set_pool_tracks")
    op.drop_index("ix_set_pool_sources_set_id", table_name="set_pool_sources")
    op.drop_table("set_pool_sources")
