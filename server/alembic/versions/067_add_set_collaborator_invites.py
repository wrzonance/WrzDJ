"""Add single-use set collaborator invite links (issue #408).

Revision ID: 067
Revises: 066
Create Date: 2026-10-03
"""

import sqlalchemy as sa

from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "set_collaborator_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["set_id"], ["sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_set_collaborator_invites_set_id", "set_collaborator_invites", ["set_id"])
    op.create_index(
        "ix_set_collaborator_invites_token_hash", "set_collaborator_invites", ["token_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_set_collaborator_invites_token_hash", table_name="set_collaborator_invites")
    op.drop_index("ix_set_collaborator_invites_set_id", table_name="set_collaborator_invites")
    op.drop_table("set_collaborator_invites")
