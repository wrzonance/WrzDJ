"""add human_verification_enforced flag

Revision ID: 8addb2680814
Revises: 040_nickname_unique
Create Date: 2026-05-01 17:30:57.801310

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "8addb2680814"
down_revision = "040_nickname_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "human_verification_enforced",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "human_verification_enforced")
