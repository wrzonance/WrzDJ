"""Add Beatport PKCE code_verifier column

Stores the PKCE code_verifier during the OAuth authorization flow
so it can be sent with the token exchange request.

Revision ID: 015
Revises: 014
Create Date: 2026-02-12 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("beatport_oauth_code_verifier", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "beatport_oauth_code_verifier")
