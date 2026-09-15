"""Drop request_votes (request_id, client_fingerprint) unique.

The legacy uq_request_vote constraint blocks legitimate votes from
distinct cookie-identified guests behind a single NAT IP. Identity-aware
dedup now relies on uq_request_vote_guest plus the existence check in
services/vote.py:_find_existing_vote().

Revision ID: 038
Revises: 037
Create Date: 2026-04-27
"""

from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("request_votes") as batch_op:
        batch_op.drop_constraint("uq_request_vote", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("request_votes") as batch_op:
        batch_op.create_unique_constraint("uq_request_vote", ["request_id", "client_fingerprint"])
