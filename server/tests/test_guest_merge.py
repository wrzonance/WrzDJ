"""Unit tests for guest merge service."""

from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.request import Request, RequestStatus
from app.models.request_vote import RequestVote
from app.models.user import User
from app.services.guest_merge import merge_guests


def _make_guest(db: Session, token_prefix: str) -> Guest:
    guest = Guest(
        token=token_prefix.ljust(64, "0"),
        fingerprint_hash=f"fp_{token_prefix}",
        created_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(guest)
    db.commit()
    db.refresh(guest)
    return guest


def test_merge_moves_requests(db: Session, test_event: Event):
    source = _make_guest(db, "src")
    target = _make_guest(db, "tgt")
    req = Request(
        event_id=test_event.id,
        song_title="Move Me",
        artist="Artist",
        source="manual",
        status=RequestStatus.NEW.value,
        dedupe_key="dk_move_me",
        guest_id=source.id,
    )
    db.add(req)
    db.commit()
    result = merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)
    assert result.requests_moved == 1
    db.refresh(req)
    assert req.guest_id == target.id


def test_merge_moves_votes(db: Session, test_event: Event):
    source = _make_guest(db, "src_v")
    target = _make_guest(db, "tgt_v")
    req = Request(
        event_id=test_event.id,
        song_title="Vote Song",
        artist="Artist",
        source="manual",
        status=RequestStatus.NEW.value,
        dedupe_key="dk_vote_song",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    vote = RequestVote(request_id=req.id, guest_id=source.id)
    db.add(vote)
    db.commit()
    result = merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)
    assert result.votes_moved == 1


def test_merge_deduplicates_votes(db: Session, test_event: Event):
    source = _make_guest(db, "src_d")
    target = _make_guest(db, "tgt_d")
    req = Request(
        event_id=test_event.id,
        song_title="Both Voted",
        artist="Artist",
        source="manual",
        status=RequestStatus.NEW.value,
        dedupe_key="dk_both_voted",
        vote_count=2,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    db.add(RequestVote(request_id=req.id, guest_id=source.id))
    db.add(RequestVote(request_id=req.id, guest_id=target.id))
    db.commit()
    result = merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)
    assert result.votes_deduped == 1
    db.refresh(req)
    assert req.vote_count == 1


def test_merge_combines_profiles(db: Session, test_event: Event):
    source = _make_guest(db, "src_p")
    target = _make_guest(db, "tgt_p")
    db.add(
        GuestProfile(
            event_id=test_event.id,
            guest_id=source.id,
            nickname="SrcNick",
            submission_count=3,
        )
    )
    db.add(
        GuestProfile(
            event_id=test_event.id,
            guest_id=target.id,
            nickname="TgtNick",
            submission_count=2,
        )
    )
    db.commit()
    result = merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)
    assert result.profiles_merged == 1
    remaining = (
        db.query(GuestProfile)
        .filter(GuestProfile.event_id == test_event.id, GuestProfile.guest_id == target.id)
        .one()
    )
    assert remaining.submission_count == 5
    assert remaining.nickname == "TgtNick"


def test_merge_moves_profile_different_event(db: Session, test_event: Event, test_user: User):
    source = _make_guest(db, "src_pe")
    target = _make_guest(db, "tgt_pe")
    other_event = Event(
        code="OTHER1",
        join_code="WX8XQG",
        name="Other Event",
        created_by_user_id=test_user.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(other_event)
    db.commit()
    db.refresh(other_event)
    db.add(
        GuestProfile(
            event_id=other_event.id,
            guest_id=source.id,
            nickname="SrcOnly",
            submission_count=1,
        )
    )
    db.commit()
    result = merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)
    assert result.profiles_moved == 1


def test_merge_nickname_fallback(db: Session, test_event: Event):
    source = _make_guest(db, "src_n")
    target = _make_guest(db, "tgt_n")
    db.add(
        GuestProfile(
            event_id=test_event.id,
            guest_id=source.id,
            nickname="SourceNick",
            submission_count=1,
        )
    )
    db.add(
        GuestProfile(
            event_id=test_event.id,
            guest_id=target.id,
            nickname=None,
            submission_count=0,
        )
    )
    db.commit()
    merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)
    remaining = (
        db.query(GuestProfile)
        .filter(GuestProfile.event_id == test_event.id, GuestProfile.guest_id == target.id)
        .one()
    )
    assert remaining.nickname == "SourceNick"


def test_merge_keeps_source_as_forwarding_tombstone(db: Session):
    """#932: the source row survives as a PII-free tombstone forwarding to the target."""
    source = _make_guest(db, "src_tomb")
    source.fingerprint_components = '{"a": 1}'
    source.user_agent = "UA"
    source.verified_email = "tomb@test.com"
    source.email_hash = "h" * 64
    source.nickname = "Nick"
    source.email_verified_at = utcnow()
    source.human_verified_at = utcnow()
    source.human_verify_count = 3
    db.commit()
    target = _make_guest(db, "tgt_tomb")
    source_token = source.token

    merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)

    db.expire_all()
    tomb = db.query(Guest).filter(Guest.id == source.id).one()
    assert tomb.merged_into_guest_id == target.id
    assert tomb.merged_at is not None
    assert tomb.token == source_token
    assert tomb.fingerprint_hash is None
    assert tomb.fingerprint_components is None
    assert tomb.user_agent is None
    assert tomb.verified_email is None
    assert tomb.email_hash is None
    assert tomb.nickname is None
    assert tomb.email_verified_at is None
    assert tomb.human_verified_at is None
    assert tomb.human_verify_count == 0
    assert db.query(Guest).filter(Guest.id == target.id).one().merged_into_guest_id is None


def test_merge_flattens_earlier_tombstones_to_one_hop(db: Session):
    """A->B then B->C leaves A forwarding straight to C."""
    a = _make_guest(db, "chain_a")
    b = _make_guest(db, "chain_b")
    c = _make_guest(db, "chain_c")
    merge_guests(db, source_guest_id=a.id, target_guest_id=b.id)
    merge_guests(db, source_guest_id=b.id, target_guest_id=c.id)

    db.expire_all()
    assert db.query(Guest).filter(Guest.id == a.id).one().merged_into_guest_id == c.id
    assert db.query(Guest).filter(Guest.id == b.id).one().merged_into_guest_id == c.id


def test_merge_returns_correct_counts(db: Session, test_event: Event):
    source = _make_guest(db, "src_cnt")
    target = _make_guest(db, "tgt_cnt")
    req = Request(
        event_id=test_event.id,
        song_title="Count Song",
        artist="Artist",
        source="manual",
        status=RequestStatus.NEW.value,
        dedupe_key="dk_count",
        guest_id=source.id,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    db.add(RequestVote(request_id=req.id, guest_id=source.id))
    db.add(GuestProfile(event_id=test_event.id, guest_id=source.id, submission_count=1))
    db.commit()
    result = merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)
    assert result.requests_moved == 1
    assert result.votes_moved == 1
    assert result.votes_deduped == 0
    assert result.profiles_moved == 1
    assert result.profiles_merged == 0


@contextmanager
def _selects_from(db: Session, table: str):
    """Collect the SELECT statements against ``table`` issued inside the block."""
    seen: list[str] = []

    def on_execute(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and table in statement:
            seen.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


def _make_event(db: Session, owner: User, code: str, join_code: str) -> Event:
    ev = Event(
        code=code,
        join_code=join_code,
        name=f"Event {code}",
        created_by_user_id=owner.id,
        expires_at=utcnow() + timedelta(hours=6),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def test_merge_reads_the_targets_votes_and_profiles_once(
    db: Session, test_event: Event, test_user: User
):
    """The target's votes and profiles are each fetched in one query, however many rows the
    source brings, instead of one lookup per source vote or profile."""
    source = _make_guest(db, "src_n1")
    target = _make_guest(db, "tgt_n1")
    events = [test_event] + [
        _make_event(db, test_user, f"NPLUS{i}", f"NP{i}XQG{i}") for i in range(1, 4)
    ]
    requests = []
    for i, ev in enumerate(events):
        req = Request(
            event_id=ev.id,
            song_title=f"Song {i}",
            artist="Artist",
            source="manual",
            status=RequestStatus.NEW.value,
            dedupe_key=f"dk_nplus_{i}",
            vote_count=2 if i % 2 == 0 else 1,
        )
        db.add(req)
        requests.append(req)
    db.commit()
    for i, (ev, req) in enumerate(zip(events, requests, strict=True)):
        db.add(RequestVote(request_id=req.id, guest_id=source.id))
        db.add(GuestProfile(event_id=ev.id, guest_id=source.id, submission_count=1))
        if i % 2 == 0:
            db.add(RequestVote(request_id=req.id, guest_id=target.id))
            db.add(GuestProfile(event_id=ev.id, guest_id=target.id, submission_count=1))
    db.commit()

    with (
        _selects_from(db, "request_votes") as vote_reads,
        _selects_from(db, "guest_profiles") as profile_reads,
    ):
        result = merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)

    assert (result.votes_moved, result.votes_deduped) == (2, 2)
    assert (result.profiles_moved, result.profiles_merged) == (2, 2)
    assert len(vote_reads) == 2, vote_reads  # the source's votes, the target's voted requests
    assert len(profile_reads) == 2, profile_reads  # the source's profiles, the target's
