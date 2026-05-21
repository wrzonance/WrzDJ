"""Add join_code to events for the collection/live event code split.

Revision ID: 045
Revises: 044
Create Date: 2026-05-20

Splits event identity into two codes per event:
- events.code keeps its existing values (becomes the COLLECTION code by intent)
- events.join_code is a NEW unique 6-char code used by /join/, /e/.../display,
  /kiosk-link/, and QR generation (the frictionless live-event code)

Backfills every existing event with a freshly-generated join_code that does
not collide with any existing code OR join_code value.
"""

import secrets
import string

import sqlalchemy as sa

from alembic import op

revision: str = "045"
down_revision: str | None = "044"
branch_labels = None
depends_on = None


# Mirrors generate_event_code() in services/event.py — kept local to the
# migration to avoid coupling to application code that may evolve.
_SAFE_ALPHABET = (
    (string.ascii_uppercase + string.digits)
    .replace("0", "")
    .replace("O", "")
    .replace("I", "")
    .replace("1", "")
)


def _generate_code(length: int = 6) -> str:
    return "".join(secrets.choice(_SAFE_ALPHABET) for _ in range(length))


def upgrade() -> None:
    # Add nullable first so existing rows don't violate the constraint
    op.add_column("events", sa.Column("join_code", sa.String(10), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM events WHERE join_code IS NULL")).fetchall()

    for (event_id,) in rows:
        while True:
            candidate = _generate_code()
            exists = conn.execute(
                sa.text("SELECT 1 FROM events WHERE code = :c OR join_code = :c LIMIT 1"),
                {"c": candidate},
            ).first()
            if not exists:
                conn.execute(
                    sa.text("UPDATE events SET join_code = :c WHERE id = :id"),
                    {"c": candidate, "id": event_id},
                )
                break

    op.alter_column("events", "join_code", nullable=False)
    op.create_index("ix_events_join_code", "events", ["join_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_events_join_code", table_name="events", if_exists=True)
    op.drop_column("events", "join_code")
