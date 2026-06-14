"""Add WrzDJSet pairing table (issue #392).

Revision ID: 058
Revises: 057
Create Date: 2026-06-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "058"
down_revision: str | None = "057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "set_pairings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_track_id", sa.String(255), nullable=False),
        sa.Column("into_track_id", sa.String(255), nullable=False),
        sa.Column("cue_in_sec", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "set_id",
            "from_track_id",
            "into_track_id",
            name="uq_set_pairing_tracks",
        ),
    )
    op.create_index("ix_set_pairings_set_id", "set_pairings", ["set_id"])
    op.create_index("ix_set_pairings_from_track_id", "set_pairings", ["from_track_id"])
    op.create_index("ix_set_pairings_into_track_id", "set_pairings", ["into_track_id"])


def downgrade() -> None:
    op.drop_index("ix_set_pairings_into_track_id", table_name="set_pairings")
    op.drop_index("ix_set_pairings_from_track_id", table_name="set_pairings")
    op.drop_index("ix_set_pairings_set_id", table_name="set_pairings")
    op.drop_table("set_pairings")
