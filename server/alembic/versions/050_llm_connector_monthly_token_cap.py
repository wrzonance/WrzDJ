"""Add monthly_token_cap to llm_connectors (issue #339).

Revision ID: 050
Revises: 049
Create Date: 2026-05-28

Adds an admin-set per-DJ monthly token cap to ``llm_connectors``:

- ``monthly_token_cap`` (Integer, nullable) — NULL means unlimited. When set,
  the LLM gateway refuses dispatch once the current calendar month's summed
  ``tokens_in + tokens_out`` for the connector meets or exceeds this value.

Nullable with no server default so existing connectors stay unlimited.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "050"
down_revision: str | None = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_connectors",
        sa.Column("monthly_token_cap", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_connectors", "monthly_token_cap")
