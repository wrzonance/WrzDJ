"""Add guests table and guest_id FKs to existing tables.

Revision ID: 036
Revises: 035_guest_profiles_event_cascade
Create Date: 2026-04-26
"""

import sqlalchemy as sa

from alembic import op

revision = "036"
down_revision = "035_guest_profiles_event_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("fingerprint_hash", sa.String(64), nullable=True),
        sa.Column("fingerprint_components", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_guests_token"), "guests", ["token"], unique=True)
    op.create_index(op.f("ix_guests_fingerprint_hash"), "guests", ["fingerprint_hash"])

    # guest_profiles: add guest_id FK + make client_fingerprint nullable
    op.add_column(
        "guest_profiles",
        sa.Column(
            "guest_id",
            sa.Integer(),
            sa.ForeignKey("guests.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_guest_profiles_guest_id"), "guest_profiles", ["guest_id"])
    op.create_unique_constraint(
        "uq_guest_profile_event_guest", "guest_profiles", ["event_id", "guest_id"]
    )
    with op.batch_alter_table("guest_profiles") as batch_op:
        batch_op.alter_column("client_fingerprint", existing_type=sa.String(64), nullable=True)

    # requests: add guest_id FK
    op.add_column(
        "requests",
        sa.Column(
            "guest_id",
            sa.Integer(),
            sa.ForeignKey("guests.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_requests_guest_id"), "requests", ["guest_id"])

    # request_votes: add guest_id FK + make client_fingerprint nullable
    op.add_column(
        "request_votes",
        sa.Column(
            "guest_id",
            sa.Integer(),
            sa.ForeignKey("guests.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_request_votes_guest_id"), "request_votes", ["guest_id"])
    op.create_unique_constraint(
        "uq_request_vote_guest", "request_votes", ["request_id", "guest_id"]
    )
    with op.batch_alter_table("request_votes") as batch_op:
        batch_op.alter_column("client_fingerprint", existing_type=sa.String(64), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("request_votes") as batch_op:
        batch_op.alter_column("client_fingerprint", existing_type=sa.String(64), nullable=False)
    op.drop_constraint("uq_request_vote_guest", "request_votes", type_="unique")
    op.drop_index(op.f("ix_request_votes_guest_id"), table_name="request_votes")
    op.drop_column("request_votes", "guest_id")

    op.drop_index(op.f("ix_requests_guest_id"), table_name="requests")
    op.drop_column("requests", "guest_id")

    with op.batch_alter_table("guest_profiles") as batch_op:
        batch_op.alter_column("client_fingerprint", existing_type=sa.String(64), nullable=False)
    op.drop_constraint("uq_guest_profile_event_guest", "guest_profiles", type_="unique")
    op.drop_index(op.f("ix_guest_profiles_guest_id"), table_name="guest_profiles")
    op.drop_column("guest_profiles", "guest_id")

    op.drop_index(op.f("ix_guests_fingerprint_hash"), table_name="guests")
    op.drop_index(op.f("ix_guests_token"), table_name="guests")
    op.drop_table("guests")
