"""Behaviour that only real Postgres enforces (SQLite does not); run with TEST_POSTGRES_URL.

CI runs these against the job's Postgres service; locally they skip unless the URL is set.
"""

from datetime import timedelta

import pytest
from sqlalchemy.exc import DataError, IntegrityError

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.user import User

pytestmark = pytest.mark.postgres


def _event(pg_db, code: str = "PGEV01") -> Event:
    user = User(username=f"pg_{code.lower()}", password_hash="x", role="dj")
    pg_db.add(user)
    pg_db.flush()
    event = Event(
        code=code,
        join_code=f"J{code[-5:]}",
        name="Postgres event",
        created_by_user_id=user.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    pg_db.add(event)
    pg_db.flush()
    return event


def _guest(pg_db, tag: str) -> Guest:
    guest = Guest(token=tag * 64, fingerprint_hash=f"fp_pg_{tag}")
    pg_db.add(guest)
    pg_db.flush()
    return guest


def test_nickname_is_unique_per_event_ignoring_case(pg_db):
    """The partial unique index on lower(nickname) (migration 040) is enforced by Postgres."""
    event = _event(pg_db)
    pg_db.add(GuestProfile(event_id=event.id, guest_id=_guest(pg_db, "a").id, nickname="Alex"))
    pg_db.flush()
    pg_db.add(GuestProfile(event_id=event.id, guest_id=_guest(pg_db, "b").id, nickname="alex"))
    with pytest.raises(IntegrityError):
        pg_db.flush()


def test_many_guests_may_have_no_nickname(pg_db):
    """The index is partial (nickname IS NOT NULL), so guests without a nickname never clash."""
    event = _event(pg_db)
    for tag in ("c", "d", "e"):
        pg_db.add(GuestProfile(event_id=event.id, guest_id=_guest(pg_db, tag).id, nickname=None))
    pg_db.flush()
    assert pg_db.query(GuestProfile).filter_by(event_id=event.id).count() == 3


def test_column_lengths_are_enforced(pg_db):
    """Postgres rejects text longer than the column (SQLite stores it): validate at the API."""
    event = _event(pg_db)
    event.name = "x" * 101  # Event.name is String(100)
    with pytest.raises(DataError):
        pg_db.flush()
