"""Detach sets from events their owner does not own.

Revision ID: 070
Revises: 069

A set's event_id is now validated against the owner when written. Rows
written before that validation may still reference an event with a
different owner; the API refuses to read through such a binding, so the
only thing it does is confuse the owner with a 404. Clear it.
"""

import sqlalchemy as sa

from alembic import op

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE sets
            SET event_id = NULL
            WHERE event_id IS NOT NULL
              AND owner_id <> (
                SELECT events.created_by_user_id FROM events WHERE events.id = sets.event_id
              )
            """
        )
    )


def downgrade() -> None:
    # Data-only migration; the cleared bindings were never valid.
    pass
