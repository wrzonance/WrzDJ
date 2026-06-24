"""Master enriched-track table (#540) — single source of truth for song data.

ISRC-first identity with a normalised artist/title signature fallback; typed
value columns for fast querying; per-field source/freshness in a ``provenance``
JSON sidecar.

Revision ID: 062
Revises: 061
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "062"
down_revision: str | None = "061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tracks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("isrc", sa.String(length=15), nullable=True),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("artist", sa.String(length=255), nullable=False),
        sa.Column("soundcharts_uuid", sa.String(length=36), nullable=True),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("musical_key", sa.String(length=20), nullable=True),
        sa.Column("camelot", sa.String(length=3), nullable=True),
        sa.Column("genre", sa.String(length=100), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("energy", sa.Integer(), nullable=True),  # 0-10; see ck_tracks_energy_range
        sa.Column("danceability", sa.Float(), nullable=True),
        sa.Column("valence", sa.Float(), nullable=True),
        sa.Column("acousticness", sa.Float(), nullable=True),
        sa.Column("instrumentalness", sa.Float(), nullable=True),
        sa.Column("speechiness", sa.Float(), nullable=True),
        sa.Column("liveness", sa.Float(), nullable=True),
        sa.Column("loudness_db", sa.Float(), nullable=True),
        sa.Column("time_signature", sa.Integer(), nullable=True),
        sa.Column("explicit", sa.Boolean(), nullable=True),
        sa.Column("artwork_url", sa.String(length=500), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isrc", name="uq_tracks_isrc"),
        sa.UniqueConstraint("signature", name="uq_tracks_signature"),
        sa.CheckConstraint("energy >= 0 AND energy <= 10", name="ck_tracks_energy_range"),
    )


def downgrade() -> None:
    op.drop_table("tracks")
