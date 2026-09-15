"""Add user role and system settings

Revision ID: 007
Revises: 006
Create Date: 2026-02-08 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add role column to users with server_default so existing users become "dj"
    op.add_column(
        "users",
        sa.Column("role", sa.String(20), nullable=False, server_default="dj"),
    )
    op.create_index("ix_users_role", "users", ["role"])

    # Promote the first user (bootstrap admin) to admin role
    op.execute("UPDATE users SET role = 'admin' WHERE id = (SELECT MIN(id) FROM users)")

    # Create system_settings table
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("registration_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "search_rate_limit_per_minute",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )

    # Insert default settings row
    op.execute(
        "INSERT INTO system_settings (id, registration_enabled, search_rate_limit_per_minute) "
        "VALUES (1, true, 30)"
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "role")
