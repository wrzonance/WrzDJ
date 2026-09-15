"""add frictionless join flags

Revision ID: a11334c031bb
Revises: 045
Create Date: 2026-05-29 20:49:39.964139

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a11334c031bb"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("frictionless_join_default", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "events",
        sa.Column("frictionless_join", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("events", "frictionless_join")
    op.drop_column("users", "frictionless_join_default")
