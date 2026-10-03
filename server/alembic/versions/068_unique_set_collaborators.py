"""Prevent duplicate SetCollaborator memberships (issue #408).

Revision ID: 068
Revises: 067
Create Date: 2026-10-03
"""

from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_set_collaborators_set_user", "set_collaborators", ["set_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_set_collaborators_set_user", "set_collaborators", type_="unique")
