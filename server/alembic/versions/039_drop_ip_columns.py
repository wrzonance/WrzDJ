"""Drop IP-derived columns from requests, request_votes, guest_profiles, guests.

Removes:
- requests.client_fingerprint (+ index ix_requests_client_fingerprint)
- request_votes.client_fingerprint (+ index ix_request_votes_client_fingerprint)
- guest_profiles.client_fingerprint (+ index ix_guest_profiles_client_fingerprint
  + unique constraint uq_guest_profile_event_fingerprint)
- guests.ip_address

Identity is now `guest_id` only (cookie + ThumbmarkJS reconciliation in
app/services/guest_identity.py). The slowapi rate-limiter remains the lone
IP consumer and uses the IP ephemerally per request.

Revision ID: 039
Revises: 038
Create Date: 2026-04-28

To restore IP-based identity, see docs/RECOVERY-IP-IDENTITY.md.
"""

import sqlalchemy as sa

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("requests") as batch_op:
        batch_op.drop_index("ix_requests_client_fingerprint")
        batch_op.drop_column("client_fingerprint")

    with op.batch_alter_table("request_votes") as batch_op:
        batch_op.drop_index("ix_request_votes_client_fingerprint")
        batch_op.drop_column("client_fingerprint")

    with op.batch_alter_table("guest_profiles") as batch_op:
        batch_op.drop_constraint("uq_guest_profile_event_fingerprint", type_="unique")
        batch_op.drop_index("ix_guest_profiles_client_fingerprint")
        batch_op.drop_column("client_fingerprint")

    with op.batch_alter_table("guests") as batch_op:
        batch_op.drop_column("ip_address")


def downgrade() -> None:
    """Full restore. See docs/RECOVERY-IP-IDENTITY.md for the broader playbook."""
    with op.batch_alter_table("guests") as batch_op:
        batch_op.add_column(sa.Column("ip_address", sa.String(length=45), nullable=True))

    with op.batch_alter_table("guest_profiles") as batch_op:
        batch_op.add_column(sa.Column("client_fingerprint", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_guest_profiles_client_fingerprint", ["client_fingerprint"])
        batch_op.create_unique_constraint(
            "uq_guest_profile_event_fingerprint",
            ["event_id", "client_fingerprint"],
        )

    with op.batch_alter_table("request_votes") as batch_op:
        batch_op.add_column(sa.Column("client_fingerprint", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_request_votes_client_fingerprint", ["client_fingerprint"])

    with op.batch_alter_table("requests") as batch_op:
        batch_op.add_column(sa.Column("client_fingerprint", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_requests_client_fingerprint", ["client_fingerprint"])
