"""Curve templates table + per-slot energy target (issue #389).

Revision ID: 055
Revises: 054
Create Date: 2026-06-09

Two changes for the WrzDJSet energy-curve editor:

- ``set_curve_templates`` — per-DJ reusable curve templates. ``points_json``
  is a JSON list of normalized points {t: 0-1, e: 0-10, label}. Built-in
  templates live in code; only user templates persist here.
- ``set_slots.target_energy`` (Float, nullable) — the slot's target energy
  (0-10, 0.1 resolution). NULL means "no explicit target"; the UI falls back
  to the track's intrinsic energy.

Re-anchored on 054 after #413 merged (053 remains reserved by sibling PR #414;
whichever of #414/#415 merges second re-anchors once more at merge time).
"""

import sqlalchemy as sa

from alembic import op

revision: str = "055"
down_revision: str | None = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "set_curve_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("points_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_set_curve_templates_user_id", "set_curve_templates", ["user_id"], unique=False
    )

    op.add_column("set_slots", sa.Column("target_energy", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("set_slots", "target_energy")
    op.drop_index("ix_set_curve_templates_user_id", table_name="set_curve_templates")
    op.drop_table("set_curve_templates")
