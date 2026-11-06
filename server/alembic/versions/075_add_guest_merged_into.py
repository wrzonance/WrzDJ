"""Add guests.merged_into_guest_id forwarding tombstone for merged guests (#932).

Revision ID: 075
Revises: 074
"""

import sqlalchemy as sa

from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("guests") as batch_op:
        batch_op.add_column(sa.Column("merged_into_guest_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("merged_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            "fk_guests_merged_into_guest_id_guests",
            "guests",
            ["merged_into_guest_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_guests_merged_into_guest_id", ["merged_into_guest_id"])


def downgrade() -> None:
    with op.batch_alter_table("guests") as batch_op:
        batch_op.drop_index("ix_guests_merged_into_guest_id")
        batch_op.drop_constraint("fk_guests_merged_into_guest_id_guests", type_="foreignkey")
        batch_op.drop_column("merged_at")
        batch_op.drop_column("merged_into_guest_id")
