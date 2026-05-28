"""Add last_health_check_at + last_health_check_status to llm_connectors.

Revision ID: 049
Revises: 048
Create Date: 2026-05-28

Adds two health-check observability columns to ``llm_connectors``:

- ``last_health_check_at`` (DateTime, nullable) — UTC timestamp of the most
  recent health check (DJ-triggered "Test" button OR the background monitor).
- ``last_health_check_status`` (String(20), nullable) — outcome of that
  health check. One of: ``"ok"``, ``"auth_invalid"``, ``"rate_limited"``,
  ``"provider_unavailable"``, ``"quota_exceeded"``, ``"error"``. Allowed
  values are enforced at the application layer (see ``connector_storage``).

Both columns are nullable because existing rows have no prior health check.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "049"
down_revision: str | None = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_connectors",
        sa.Column("last_health_check_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "llm_connectors",
        sa.Column("last_health_check_status", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_connectors", "last_health_check_status")
    op.drop_column("llm_connectors", "last_health_check_at")
