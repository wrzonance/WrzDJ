"""Behaviour that only real Postgres enforces (SQLite does not); run with TEST_POSTGRES_URL.

CI runs these against the job's Postgres service; locally they skip unless the URL is set.
"""

import threading
from datetime import timedelta

import pytest
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.user import User
from app.services.guest_identity import identify_guest, resolve_guest_by_token
from app.services.guest_merge import merge_guests

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


# --- identify vs merge row locks (#951): two sessions on two connections ---------------

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/125.0 Safari/537.36"


def _seed_pair(engine, tag: str) -> tuple[int, int, str]:
    """A committed source and target guest; returns (source_id, target_id, source_token)."""
    source_token, target_token = f"{tag}s".ljust(64, "0"), f"{tag}t".ljust(64, "0")
    with Session(engine) as s:
        source = Guest(token=source_token, fingerprint_hash=f"fp_{tag}_source", user_agent=_UA)
        target = Guest(token=target_token, fingerprint_hash=f"fp_{tag}_target", user_agent=_UA)
        s.add_all([source, target])
        s.commit()
        return source.id, target.id, source_token


def _run(fn, *args) -> tuple[threading.Thread, dict]:
    box: dict = {}

    def target():
        try:
            box["value"] = fn(*args)
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertions below
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


def test_identify_waits_for_an_in_flight_merge_and_lands_on_the_survivor(_pg_engine):
    """#951: a merge holds the source row; the identify for that cookie blocks on it, then
    reads the committed tombstone and answers with the survivor, writing nothing back."""
    if _pg_engine is None:
        pytest.skip("TEST_POSTGRES_URL is not set")
    source_id, target_id, source_token = _seed_pair(_pg_engine, "lock1")

    merging = Session(_pg_engine)
    merging.commit = merging.flush  # run the real merge, but hold its transaction open
    merge_guests(merging, source_guest_id=source_id, target_guest_id=target_id)

    def identify(token):
        with Session(_pg_engine) as s:
            return identify_guest(
                s,
                token_from_cookie=token,
                fingerprint_hash="fp_lock1_device",
                fingerprint_components=None,
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1",
            )

    thread, box = _run(identify, source_token)
    thread.join(0.5)
    assert thread.is_alive(), "identify did not wait for the merge's row lock"

    Session.commit(merging)
    merging.close()
    thread.join(10)
    assert not thread.is_alive() and "error" not in box, box
    assert (box["value"].guest_id, box["value"].action) == (target_id, "cookie_hit")
    with Session(_pg_engine) as s:
        tomb = s.get(Guest, source_id)
        assert tomb.merged_into_guest_id == target_id
        assert tomb.fingerprint_hash is None and tomb.user_agent is None


def test_merge_waits_for_an_in_flight_identify_and_still_clears_the_tombstone(_pg_engine):
    """#951: an identify holds the source row while writing it; the merge blocks until that
    commits and then clears the tombstone, so the identify's writes never outlive the merge."""
    if _pg_engine is None:
        pytest.skip("TEST_POSTGRES_URL is not set")
    source_id, target_id, source_token = _seed_pair(_pg_engine, "lock2")

    identifying = Session(_pg_engine)
    guest = resolve_guest_by_token(identifying, source_token, lock=True)
    guest.fingerprint_hash = "fp_lock2_device"
    identifying.flush()

    def merge():
        with Session(_pg_engine) as s:
            return merge_guests(s, source_guest_id=source_id, target_guest_id=target_id)

    thread, box = _run(merge)
    thread.join(0.5)
    assert thread.is_alive(), "merge did not wait for identify's row lock"

    identifying.commit()
    identifying.close()
    thread.join(10)
    assert not thread.is_alive() and "error" not in box, box
    with Session(_pg_engine) as s:
        tomb = s.get(Guest, source_id)
        assert tomb.merged_into_guest_id == target_id
        assert tomb.fingerprint_hash is None
