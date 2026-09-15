"""Email verification: add columns to guests, create codes table, drop GuestProfile.email.

Revision ID: 037
Revises: 036
Create Date: 2026-04-27
"""

import sqlalchemy as sa

from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guests", sa.Column("verified_email", sa.Text(), nullable=True))
    op.add_column("guests", sa.Column("email_hash", sa.String(64), nullable=True))
    op.add_column("guests", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column("guests", sa.Column("nickname", sa.String(30), nullable=True))
    op.create_index(op.f("ix_guests_email_hash"), "guests", ["email_hash"], unique=True)

    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guest_id", sa.Integer(), nullable=False),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["guest_id"], ["guests.id"], ondelete="CASCADE"),
    )
    op.create_index(
        op.f("ix_email_verification_codes_guest_id"),
        "email_verification_codes",
        ["guest_id"],
    )
    op.create_index(
        op.f("ix_email_verification_codes_email_hash"),
        "email_verification_codes",
        ["email_hash"],
    )

    with op.batch_alter_table("guest_profiles") as batch_op:
        batch_op.drop_column("email")


def downgrade() -> None:
    with op.batch_alter_table("guest_profiles") as batch_op:
        batch_op.add_column(sa.Column("email", sa.Text(), nullable=True))

    op.drop_index(
        op.f("ix_email_verification_codes_email_hash"),
        table_name="email_verification_codes",
    )
    op.drop_index(
        op.f("ix_email_verification_codes_guest_id"),
        table_name="email_verification_codes",
    )
    op.drop_table("email_verification_codes")

    op.drop_index(op.f("ix_guests_email_hash"), table_name="guests")
    op.drop_column("guests", "nickname")
    op.drop_column("guests", "email_verified_at")
    op.drop_column("guests", "email_hash")
    op.drop_column("guests", "verified_email")
