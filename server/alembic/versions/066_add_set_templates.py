"""Add set_templates table (issue #407).

A template snapshots a source Set's target settings plus its slot skeleton
(position/locked/target_energy/notes, no track assignments) and energy curve
as JSON (``slots_json`` / ``curve_points_json``). Mirrors the flat-table shape
of ``set_curve_templates`` (#389) — see app/models/set_template.py.

Revision ID: 066
Revises: 065
Create Date: 2026-06-27
"""

import sqlalchemy as sa

from alembic import op

revision: str = "066"
down_revision: str | None = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "set_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("vibe_theme", sa.String(length=50), nullable=True),
        sa.Column("target_duration_sec", sa.Integer(), nullable=True),
        sa.Column(
            "avg_transition_overlap_sec",
            sa.Integer(),
            nullable=False,
            server_default="8",
        ),
        sa.Column("bpm_floor", sa.Integer(), nullable=True),
        sa.Column("bpm_ceiling", sa.Integer(), nullable=True),
        sa.Column(
            "key_strictness",
            sa.Float(),
            nullable=False,
            server_default="0.2",
        ),
        sa.Column("slots_json", sa.Text(), nullable=False),
        sa.Column("curve_points_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_set_templates_user_id", "set_templates", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_set_templates_user_id", table_name="set_templates")
    op.drop_table("set_templates")
