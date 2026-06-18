"""Add accepted_at to requests.

Issue #478: the DJ "date accepted" sort needs a real first-accepted timestamp.
``updated_at`` is unsuitable because it moves on every later status change and
metadata refresh, so sorting on it would reorder rows long after acceptance.

Revision ID: 061
Revises: 060
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "061"
down_revision: str | None = "060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("accepted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_requests_accepted_at", "requests", ["accepted_at"])
    # Best-effort backfill: rows already past acceptance get updated_at as an
    # approximate accepted_at so existing accepted/playing/played requests sort
    # sensibly. Pre-migration values are approximate (documented in #478); rows
    # never accepted stay NULL and sort null-last.
    op.execute(
        "UPDATE requests SET accepted_at = updated_at "
        "WHERE status IN ('accepted', 'playing', 'played') AND accepted_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_requests_accepted_at", table_name="requests")
    op.drop_column("requests", "accepted_at")
