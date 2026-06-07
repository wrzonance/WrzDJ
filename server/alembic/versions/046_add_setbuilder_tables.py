"""Add WrzDJSet Phase 0 tables (sets, slots, curve points, collaborators, vibes)

Revision ID: 046
Revises: a11334c031bb
Create Date: 2026-06-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "046"
down_revision: str | None = "a11334c031bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("vibe_theme", sa.String(50), nullable=True),
        sa.Column("target_duration_sec", sa.Integer(), nullable=True),
        sa.Column("bpm_floor", sa.Integer(), nullable=True),
        sa.Column("bpm_ceiling", sa.Integer(), nullable=True),
        sa.Column("key_strictness", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("sharing_mode", sa.String(20), nullable=False, server_default="private"),
        sa.Column("tidal_playlist_id", sa.String(100), nullable=True),
        sa.Column("exported_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sets_owner_id", "sets", ["owner_id"])
    op.create_index("ix_sets_event_id", "sets", ["event_id"])

    op.create_table(
        "set_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.String(255), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("transition_score", sa.Float(), nullable=True),
        sa.Column("transition_warnings", sa.Text(), nullable=True),
    )
    op.create_index("ix_set_slots_set_id", "set_slots", ["set_id"])
    op.create_index("ix_set_slots_track_id", "set_slots", ["track_id"])

    op.create_table(
        "set_curve_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position_sec", sa.Integer(), nullable=False),
        sa.Column("energy", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(50), nullable=True),
        sa.Column("is_slow_window_start", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_slow_window_end", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_index("ix_set_curve_points_set_id", "set_curve_points", ["set_id"])

    op.create_table(
        "set_collaborators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id",
            sa.Integer(),
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "invited_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("invited_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_set_collaborators_set_id", "set_collaborators", ["set_id"])
    op.create_index("ix_set_collaborators_user_id", "set_collaborators", ["user_id"])

    op.create_table(
        "track_vibes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("track_id", sa.String(255), nullable=False),
        sa.Column("energy", sa.Integer(), nullable=True),
        sa.Column("mood", sa.String(50), nullable=True),
        sa.Column("era", sa.String(50), nullable=True),
        sa.Column("sing_along", sa.Boolean(), nullable=True),
        sa.Column("dance_floor", sa.Boolean(), nullable=True),
        sa.Column("transitional_role", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("llm_provider", sa.String(50), nullable=False),
        sa.Column("llm_model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "track_id",
            "llm_provider",
            "llm_model",
            "prompt_version",
            "schema_version",
            name="uq_track_vibe_identity",
        ),
    )
    op.create_index("ix_track_vibes_track_id", "track_vibes", ["track_id"])

    op.create_table(
        "track_vibe_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("track_id", sa.String(255), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("energy_override", sa.Integer(), nullable=True),
        sa.Column("mood_override", sa.String(50), nullable=True),
        sa.Column(
            "overridden_from_vibe_id",
            sa.Integer(),
            sa.ForeignKey("track_vibes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("energy_was", sa.Integer(), nullable=True),
        sa.Column("mood_was", sa.String(50), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_track_vibe_overrides_track_id", "track_vibe_overrides", ["track_id"])
    op.create_index("ix_track_vibe_overrides_user_id", "track_vibe_overrides", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_track_vibe_overrides_user_id")
    op.drop_index("ix_track_vibe_overrides_track_id")
    op.drop_table("track_vibe_overrides")
    op.drop_index("ix_track_vibes_track_id")
    op.drop_table("track_vibes")
    op.drop_index("ix_set_collaborators_user_id")
    op.drop_index("ix_set_collaborators_set_id")
    op.drop_table("set_collaborators")
    op.drop_index("ix_set_curve_points_set_id")
    op.drop_table("set_curve_points")
    op.drop_index("ix_set_slots_track_id")
    op.drop_index("ix_set_slots_set_id")
    op.drop_table("set_slots")
    op.drop_index("ix_sets_event_id")
    op.drop_index("ix_sets_owner_id")
    op.drop_table("sets")
