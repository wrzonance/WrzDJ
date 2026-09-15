"""guest_profiles.event_id ON DELETE CASCADE

When pre-event collection (PR #245, migration 034) added the
guest_profiles table, the event_id FK was created without ON DELETE
CASCADE. As a result, deleting an event that ever received a guest
collect submission 500'd with ForeignKeyViolation. Bring the
constraint in line with now_playing and play_history, which were
declared CASCADE from the start.

Surfaced by exploratory headless testing of the LOC-reduction refactor
branch (PR #248).

Revision ID: 035_guest_profiles_event_cascade
Revises: 034
Create Date: 2026-04-25
"""

from alembic import op

revision = "035_guest_profiles_event_cascade"
down_revision = "034"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "guest_profiles_event_id_fkey"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "guest_profiles", type_="foreignkey")
    op.create_foreign_key(
        CONSTRAINT_NAME,
        "guest_profiles",
        "events",
        ["event_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "guest_profiles", type_="foreignkey")
    op.create_foreign_key(
        CONSTRAINT_NAME,
        "guest_profiles",
        "events",
        ["event_id"],
        ["id"],
    )
