"""Add raw_search_query and sync_results_json to requests table

Revision ID: 012
Revises: 011
Create Date: 2026-02-12 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requests",
        sa.Column("raw_search_query", sa.String(200), nullable=True),
    )
    op.add_column(
        "requests",
        sa.Column("sync_results_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("requests", "sync_results_json")
    op.drop_column("requests", "raw_search_query")
