"""Behaviour that only real Postgres enforces (SQLite does not); run with TEST_POSTGRES_URL.

CI runs these against the job's Postgres service; locally they skip unless the URL is set.
"""

import hashlib
import threading
import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import Request as HttpRequest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.core.rate_limit import get_guest_id
from app.core.time import utcnow
from app.models.email_verification_code import EmailVerificationCode
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.email_verification import (
    CodeInvalidError,
    RateLimitExceededError,
    _email_lock_key,
    _serialize_per_email,
    confirm_verification_code,
    create_verification_code,
)
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


# --- identify / merge / guest writes vs merge: row locks (#951) -----------------------
# Each test holds one real transaction open (session.commit swapped for flush), starts the
# other operation on a second connection, proves through pg_stat_activity that it is waiting
# on a row lock, releases, and checks where the waiting operation landed.

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/125.0 Safari/537.36"


def _engine_or_skip(engine):
    if engine is None:
        pytest.skip("TEST_POSTGRES_URL is not set")
    return engine


def _seed_guests(engine, tag: str, *names: str) -> dict[str, Guest]:
    """Committed guests keyed by name; tokens are ``<tag><name>`` padded to 64."""
    with Session(engine) as s:
        guests = {
            name: Guest(
                token=f"{tag}{name}".ljust(64, "0"),
                fingerprint_hash=f"fp_{tag}_{name}",
                user_agent=_UA,
                last_seen_at=utcnow() - timedelta(hours=2),
            )
            for name in names
        }
        s.add_all(guests.values())
        s.commit()
        for guest in guests.values():
            s.refresh(guest)
            s.expunge(guest)
    return guests


def _seed_request(engine, tag: str, guest_id: int) -> int:
    with Session(engine) as s:
        user = User(username=f"pg_{tag}", password_hash="x", role="dj")
        s.add(user)
        s.flush()
        event = Event(
            code=f"L{tag[-5:].upper()}",
            join_code=f"J{tag[-5:].upper()}",
            name="lock event",
            created_by_user_id=user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        s.add(event)
        s.flush()
        request = Request(
            event_id=event.id,
            guest_id=guest_id,
            song_title="Held",
            artist="Artist",
            source="manual",
            status=RequestStatus.NEW.value,
            dedupe_key=f"dk_{tag}",
        )
        s.add(request)
        s.commit()
        return request.id


@pytest.fixture
def held():
    """Sessions whose locks a test holds open; rolled back at teardown if the test failed
    before releasing them, so a failure never leaves the schema drop blocked."""
    sessions: list[Session] = []
    yield sessions
    for session in sessions:
        if session.is_active:
            session.rollback()
        session.close()


def _holding(engine, held: list[Session]) -> Session:
    """A session whose commit only flushes, so its row locks stay held until released."""
    session = Session(engine)
    session.commit = session.flush
    held.append(session)
    return session


def _release(session) -> None:
    Session.commit(session)
    session.close()


def _in_thread(fn, *args, **kwargs) -> tuple[threading.Thread, dict]:
    box: dict = {}

    def target():
        try:
            box["value"] = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertions below
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box


def _assert_waiting_on_row_lock(engine, thread: threading.Thread, timeout: float = 30.0):
    """The other backend must reach a row-lock wait (pg_stat_activity), not merely be slow.

    The window is generous because CI runs four xdist workers under coverage on one runner;
    a thread that finishes without ever waiting fails immediately regardless."""
    deadline = time.monotonic() + timeout
    with engine.connect() as conn:
        while time.monotonic() < deadline:
            waiting = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                    " AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                )
            ).scalar()
            if waiting:
                assert thread.is_alive()
                return
            if not thread.is_alive():
                raise AssertionError("the operation finished without waiting on a row lock")
            time.sleep(0.02)
    raise AssertionError("no backend reached a row-lock wait")


def _finish(thread: threading.Thread, box: dict) -> object:
    thread.join(30)
    assert not thread.is_alive() and "error" not in box, box
    return box["value"]


def _load(engine, guest_id: int) -> Guest:
    with Session(engine) as s:
        guest = s.get(Guest, guest_id)
        s.expunge(guest)
        return guest


def _identify(engine, **kwargs):
    with Session(engine) as s:
        return identify_guest(s, **kwargs)


def _merge(engine, source_id: int, target_id: int):
    with Session(engine) as s:
        return merge_guests(s, source_guest_id=source_id, target_guest_id=target_id)


def test_identify_waits_for_an_in_flight_merge_and_lands_on_the_survivor(_pg_engine, held):
    """A merge holds the source row; the identify for that cookie waits, then reads the
    committed tombstone and answers with the survivor, writing nothing back."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "lk1", "a", "b")
    merging = _holding(engine, held)
    merge_guests(merging, source_guest_id=g["a"].id, target_guest_id=g["b"].id)

    thread, box = _in_thread(
        _identify,
        engine,
        token_from_cookie=g["a"].token,
        fingerprint_hash="fp_lk1_device",
        fingerprint_components=None,
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1",
    )
    _assert_waiting_on_row_lock(engine, thread)
    _release(merging)

    result = _finish(thread, box)
    assert (result.guest_id, result.action) == (g["b"].id, "cookie_hit")
    tomb = _load(engine, g["a"].id)
    assert tomb.merged_into_guest_id == g["b"].id
    assert tomb.fingerprint_hash is None and tomb.user_agent is None


def test_merge_waits_for_an_in_flight_identify_and_still_clears_the_tombstone(_pg_engine, held):
    """An identify holds the source row while writing it; the merge waits for that commit
    and then clears the tombstone, so the identify's writes never outlive the merge."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "lk2", "a", "b")
    identifying = Session(engine)
    held.append(identifying)  # released at teardown if an assertion fires before commit
    guest = resolve_guest_by_token(identifying, g["a"].token, lock=True)
    guest.fingerprint_hash = "fp_lk2_device"
    identifying.flush()

    thread, box = _in_thread(_merge, engine, g["a"].id, g["b"].id)
    _assert_waiting_on_row_lock(engine, thread)
    identifying.commit()
    identifying.close()

    _finish(thread, box)
    tomb = _load(engine, g["a"].id)
    assert tomb.merged_into_guest_id == g["b"].id and tomb.fingerprint_hash is None


def test_merge_into_a_target_being_merged_away_lands_on_its_survivor(_pg_engine, held):
    """A→B waits while B→C is in flight, then re-reads B as a tombstone and merges A into C
    directly: nothing is left on B and A forwards to C in one hop."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "lk3", "a", "b", "c")
    request_id = _seed_request(engine, "lk3req", g["a"].id)
    merging = _holding(engine, held)
    merge_guests(merging, source_guest_id=g["b"].id, target_guest_id=g["c"].id)

    thread, box = _in_thread(_merge, engine, g["a"].id, g["b"].id)
    _assert_waiting_on_row_lock(engine, thread)
    _release(merging)

    result = _finish(thread, box)
    assert result.target_guest_id == g["c"].id and result.requests_moved == 1
    assert _load(engine, g["a"].id).merged_into_guest_id == g["c"].id
    with Session(engine) as s:
        assert s.get(Request, request_id).guest_id == g["c"].id


def test_merge_refuses_a_source_that_was_merged_away_meanwhile(_pg_engine, held):
    """A→C waits while A→B is in flight; under the lock A is a tombstone, so the second
    merge is refused instead of moving B's data back out through A."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "lk4", "a", "b", "c")
    merging = _holding(engine, held)
    merge_guests(merging, source_guest_id=g["a"].id, target_guest_id=g["b"].id)

    thread, box = _in_thread(_merge, engine, g["a"].id, g["c"].id)
    _assert_waiting_on_row_lock(engine, thread)
    _release(merging)

    thread.join(30)
    assert isinstance(box.get("error"), ValueError), box
    assert _load(engine, g["a"].id).merged_into_guest_id == g["b"].id


def test_fingerprint_reconcile_waits_and_does_not_revive_a_merged_guest(_pg_engine, held):
    """A cookieless identify picks live A by fingerprint while A→B is in flight; under the
    lock A is a tombstone, so it creates a new guest rather than rewriting A's token."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "lk5", "a", "b")
    merging = _holding(engine, held)
    merge_guests(merging, source_guest_id=g["a"].id, target_guest_id=g["b"].id)

    thread, box = _in_thread(
        _identify,
        engine,
        token_from_cookie=None,
        fingerprint_hash=g["a"].fingerprint_hash,
        fingerprint_components=None,
        user_agent=_UA,
    )
    _assert_waiting_on_row_lock(engine, thread)
    _release(merging)

    result = _finish(thread, box)
    assert result.action == "create" and result.guest_id not in (g["a"].id, g["b"].id)
    tomb = _load(engine, g["a"].id)
    assert tomb.token == g["a"].token and tomb.fingerprint_hash is None


def test_a_guest_write_during_a_merge_resolves_to_the_survivor(_pg_engine, held):
    """The guest-id chokepoint for a writing request waits on the merge and then resolves
    the cookie to the survivor, so the request it is about to insert cannot land on the
    tombstone after the merge's sweep."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "lk6", "a", "b")
    merging = _holding(engine, held)
    merge_guests(merging, source_guest_id=g["a"].id, target_guest_id=g["b"].id)

    def resolve_for_write():
        with Session(engine) as s:
            cookie = f"wrzdj_guest={g['a'].token}".encode()
            request = HttpRequest(
                {"type": "http", "method": "POST", "headers": [(b"cookie", cookie)]}
            )
            return get_guest_id(request, s)

    thread, box = _in_thread(resolve_for_write)
    _assert_waiting_on_row_lock(engine, thread)
    _release(merging)
    assert _finish(thread, box) == g["b"].id


def test_identify_through_a_tombstone_while_its_survivor_is_merged_does_not_deadlock(
    _pg_engine, held
):
    """A→B exists; B→C is in flight and holds A, B and C (a merge locks the source's own
    tombstones with it, in id order, in its first step). An identify with A's cookie waits
    once and ends on C. Before that single ordered lock step, a merge took A only when it
    flattened the chain at the end, so an identify holding A and waiting for B deadlocked
    with it (reproduced mid-merge in review); this pins the end state of the scenario."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "lk7", "a", "b", "c")
    _merge(engine, g["a"].id, g["b"].id)
    merging = _holding(engine, held)
    merge_guests(merging, source_guest_id=g["b"].id, target_guest_id=g["c"].id)

    thread, box = _in_thread(
        _identify,
        engine,
        token_from_cookie=g["a"].token,
        fingerprint_hash="fp_lk7_device",
        fingerprint_components=None,
        user_agent=_UA,
    )
    _assert_waiting_on_row_lock(engine, thread)
    _release(merging)

    result = _finish(thread, box)
    assert (result.guest_id, result.action) == (g["c"].id, "cookie_hit")
    assert _load(engine, g["a"].id).merged_into_guest_id == g["c"].id


# --- verification codes: one request per email at a time, one confirmation per code ------


def test_code_requests_for_one_email_are_serialized(_pg_engine, held):
    """The hourly count and the insert run under a per-email advisory lock, so a request for
    an address waits for whoever holds that lock instead of reading a count that is about to
    change."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "vc1", "a")
    key = _email_lock_key(hashlib.sha256(b"fan-vc1@test.com").hexdigest())
    holding = _holding(engine, held)
    holding.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def request_code():
        with Session(engine) as s, patch("app.services.email_verification.send_verification_email"):
            return create_verification_code(s, guest_id=g["a"].id, email="fan-vc1@test.com").id

    thread, box = _in_thread(request_code)
    _assert_waiting_on_row_lock(engine, thread)
    _release(holding)
    code_id = _finish(thread, box)
    with Session(engine) as s:
        assert s.get(EmailVerificationCode, code_id).guest_id == g["a"].id


def test_concurrent_code_requests_cannot_overshoot_the_hourly_cap(_pg_engine):
    """Four sends in the hour, then two real requests at once: exactly one more is sent and
    the other is rate-limited, so the address ends the hour at the cap, never above it."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "vc3", "a")
    email = "fan-vc3@test.com"
    with Session(engine) as s, patch("app.services.email_verification.send_verification_email"):
        for _ in range(4):
            create_verification_code(s, guest_id=g["a"].id, email=email)

    def request_code():
        with Session(engine) as s, patch("app.services.email_verification.send_verification_email"):
            return create_verification_code(s, guest_id=g["a"].id, email=email).id

    threads = [_in_thread(request_code) for _ in range(2)]
    outcomes = []
    for thread, box in threads:
        thread.join(30)
        assert not thread.is_alive()
        outcomes.append(box.get("error", box.get("value")))
    errors = [o for o in outcomes if isinstance(o, RateLimitExceededError)]
    assert len(errors) == 1, outcomes
    with Session(engine) as s:
        eh = hashlib.sha256(email.encode()).hexdigest()
        count = (
            s.query(EmailVerificationCode).filter(EmailVerificationCode.email_hash == eh).count()
        )
    assert count == 5


def test_a_code_cannot_be_accepted_twice_by_concurrent_confirmations(_pg_engine, held):
    """The first confirmation (the real service, its transaction held open) marks the code
    used under FOR UPDATE; a second confirmation of the same code waits for it and is then
    refused instead of accepting the code again."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "vc2", "a")
    email = "fan-vc2@test.com"
    with Session(engine) as s, patch("app.services.email_verification.send_verification_email"):
        row = create_verification_code(s, guest_id=g["a"].id, email=email)
        code, row_id = row.code, row.id
    first = _holding(engine, held)
    assert confirm_verification_code(first, guest_id=g["a"].id, email=email, code=code).verified

    def confirm_again():
        with Session(engine) as s:
            return confirm_verification_code(s, guest_id=g["a"].id, email=email, code=code).verified

    thread, box = _in_thread(confirm_again)
    _assert_waiting_on_row_lock(engine, thread)
    _release(first)
    thread.join(30)
    assert not thread.is_alive()
    assert isinstance(box.get("error"), CodeInvalidError), box
    with Session(engine) as s:
        assert s.get(EmailVerificationCode, row_id).used is True


def test_two_guests_confirming_one_email_are_serialized_and_the_second_merges(_pg_engine, held):
    """Guest A's confirmation holds the per-email ownership lock after taking the address; B's
    confirmation of the same address waits for it, then sees A as the owner and merges into
    A instead of both guests ending up with the email."""
    engine = _engine_or_skip(_pg_engine)
    g = _seed_guests(engine, "vc4", "a", "b")
    email = "fan-vc4@test.com"
    eh = hashlib.sha256(email.encode()).hexdigest()
    with Session(engine) as s, patch("app.services.email_verification.send_verification_email"):
        code_a = create_verification_code(s, guest_id=g["a"].id, email=email).code
        code_b = create_verification_code(s, guest_id=g["b"].id, email=email).code

    first = _holding(engine, held)
    assert confirm_verification_code(first, guest_id=g["a"].id, email=email, code=code_a).verified
    assert first.get(Guest, g["a"].id).email_hash == eh  # A owns it, uncommitted
    _serialize_per_email(first, eh)  # the lock the real confirm holds until its commit

    def confirm_b():
        with Session(engine) as s:
            return confirm_verification_code(s, guest_id=g["b"].id, email=email, code=code_b)

    thread, box = _in_thread(confirm_b)
    _assert_waiting_on_row_lock(engine, thread)
    _release(first)
    result = _finish(thread, box)
    assert (result.merged, result.guest_id) == (True, g["a"].id)
    with Session(engine) as s:
        assert s.get(Guest, g["b"].id).merged_into_guest_id == g["a"].id
        assert s.get(Guest, g["b"].id).email_hash is None
