"""add frictionless join flags

Revision ID: a11334c031bb
Revises: 051
Create Date: 2026-05-29 20:49:39.964139

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a11334c031bb"
down_revision: str | None = "051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
