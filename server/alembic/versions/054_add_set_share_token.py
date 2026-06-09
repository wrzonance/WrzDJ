"""Add share_token to sets (issue #398).

Revision ID: 054
Revises: 052
Create Date: 2026-06-09

Nullable CSPRNG token enabling read-only public sharing of a set.
NULL means not shared; revoke nulls it, regenerate overwrites it.
The unique index gives constant-pattern indexed lookup on the public
share route (no table scans, no timing oracle beyond the index probe).

Slot note: anchored on 052; sibling PR #388 holds slot 053 — whichever
merges second re-anchors its down_revision.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "054"
down_revision: str | None = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sets", sa.Column("share_token", sa.String(length=64), nullable=True))
    op.create_index("ix_sets_share_token", "sets", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sets_share_token", table_name="sets")
    op.drop_column("sets", "share_token")
