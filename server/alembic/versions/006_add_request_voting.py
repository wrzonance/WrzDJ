"""Add request voting

Revision ID: 006
Revises: 005
Create Date: 2026-02-06 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add vote_count column to requests with CHECK constraint
    op.add_column(
        "requests",
        sa.Column("vote_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_vote_count_non_negative",
        "requests",
        "vote_count >= 0",
    )

    # Create request_votes table with CASCADE delete
    op.create_table(
        "request_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "request_id",
            sa.Integer(),
            sa.ForeignKey("requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("request_id", "client_fingerprint", name="uq_request_vote"),
    )
    op.create_index("ix_request_votes_request_id", "request_votes", ["request_id"])
    op.create_index("ix_request_votes_client_fingerprint", "request_votes", ["client_fingerprint"])


def downgrade() -> None:
    op.drop_table("request_votes")
    op.drop_constraint("ck_vote_count_non_negative", "requests", type_="check")
    op.drop_column("requests", "vote_count")
