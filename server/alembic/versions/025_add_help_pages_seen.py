"""Add help_pages_seen to users table

Revision ID: 025
Revises: 024
Create Date: 2026-02-16 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("help_pages_seen", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "help_pages_seen")
