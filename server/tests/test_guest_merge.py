"""Unit tests for guest merge service."""

from datetime import timedelta

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


def test_merge_deletes_source_guest(db: Session):
    source = _make_guest(db, "src_del")
    target = _make_guest(db, "tgt_del")
    merge_guests(db, source_guest_id=source.id, target_guest_id=target.id)
    assert db.query(Guest).filter(Guest.id == source.id).first() is None
    assert db.query(Guest).filter(Guest.id == target.id).first() is not None


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
