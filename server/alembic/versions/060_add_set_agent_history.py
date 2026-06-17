"""Persist WrzDJSet agent chat sessions.

Revision ID: 060
Revises: 059
Create Date: 2026-06-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "060"
down_revision: str | None = "059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "set_agent_sessions",
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
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("compacted_through_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("set_id", "user_id", name="uq_set_agent_session_set_user"),
    )
    op.create_index("ix_set_agent_sessions_set_id", "set_agent_sessions", ["set_id"])
    op.create_index("ix_set_agent_sessions_user_id", "set_agent_sessions", ["user_id"])

    op.create_table(
        "set_agent_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("set_agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("display_summary", sa.Text(), nullable=True),
        sa.Column("tool_calls_json", sa.Text(), nullable=True),
        sa.Column("affected_transition_scores_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_set_agent_messages_session_id", "set_agent_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_set_agent_messages_session_id", table_name="set_agent_messages")
    op.drop_table("set_agent_messages")
    op.drop_index("ix_set_agent_sessions_user_id", table_name="set_agent_sessions")
    op.drop_index("ix_set_agent_sessions_set_id", table_name="set_agent_sessions")
    op.drop_table("set_agent_sessions")
