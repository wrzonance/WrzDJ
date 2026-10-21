"""Record Turnstile passes per guest for the admin Guests page (#862).

Revision ID: 074
Revises: 073
"""

import sqlalchemy as sa

from alembic import op

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guests", sa.Column("human_verified_at", sa.DateTime(), nullable=True))
    op.add_column(
        "guests",
        sa.Column("human_verify_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("guests", "human_verify_count")
    op.drop_column("guests", "human_verified_at")
