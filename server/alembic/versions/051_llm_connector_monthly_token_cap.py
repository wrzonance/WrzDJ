"""Add monthly_token_cap to llm_connectors (issue #339).

Revision ID: 051
Revises: 050
Create Date: 2026-05-28

Adds an admin-set per-DJ monthly token cap to ``llm_connectors``:

- ``monthly_token_cap`` (Integer, nullable) — NULL means unlimited. When set,
  the LLM gateway refuses dispatch once the current calendar month's summed
  ``tokens_in + tokens_out`` for the connector meets or exceeds this value.

Nullable with no server default so existing connectors stay unlimited.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "051"
down_revision: str | None = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_connectors",
        sa.Column("monthly_token_cap", sa.Integer(), nullable=True),
    )
    # Defence-in-depth: the API schema (ge=0) and service layer already reject
    # negatives, but a DB CHECK guarantees a bad write can never persist a
    # negative cap (which would make the connector permanently "over budget").
    op.create_check_constraint(
        "ck_llm_connectors_monthly_token_cap_nonnegative",
        "llm_connectors",
        "monthly_token_cap IS NULL OR monthly_token_cap >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_llm_connectors_monthly_token_cap_nonnegative",
        "llm_connectors",
        type_="check",
    )
    op.drop_column("llm_connectors", "monthly_token_cap")
