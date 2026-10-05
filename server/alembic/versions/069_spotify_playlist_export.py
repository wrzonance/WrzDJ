"""Add encrypted Spotify OAuth tokens and SetBuilder playlist export ids.

Revision ID: 069
Revises: 068
"""

import sqlalchemy as sa

from alembic import op
from app.core.encryption import EncryptedText

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("spotify_access_token", EncryptedText(), nullable=True))
    op.add_column("users", sa.Column("spotify_refresh_token", EncryptedText(), nullable=True))
    op.add_column("users", sa.Column("spotify_token_expires_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("spotify_oauth_state", EncryptedText(), nullable=True))
    op.add_column("sets", sa.Column("spotify_playlist_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("sets", "spotify_playlist_id")
    op.drop_column("users", "spotify_oauth_state")
    op.drop_column("users", "spotify_token_expires_at")
    op.drop_column("users", "spotify_refresh_token")
    op.drop_column("users", "spotify_access_token")
