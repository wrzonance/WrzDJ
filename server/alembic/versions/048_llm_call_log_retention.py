"""Configurable llm_call_log retention.

Revision ID: 048
Revises: 047
Create Date: 2026-05-26

Adds system_settings.llm_call_log_retention_days (int, default 30, NOT NULL).
The daily cleanup job reads this value each run; sanity bounds (7..365) are
enforced at the API level, not the database.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "048"
down_revision: str | None = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "llm_call_log_retention_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "llm_call_log_retention_days")
