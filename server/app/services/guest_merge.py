"""Guest merge service — consolidates two Guest records into one."""

from dataclasses import dataclass

from sqlalchemy import case, update
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.request import Request
from app.models.request_vote import RequestVote
from app.services.guest_identity import LOCK_RETRIES, MAX_MERGE_HOPS, lock_guests


@dataclass
class MergeResult:
    source_guest_id: int
    target_guest_id: int
    requests_moved: int
    votes_moved: int
    votes_deduped: int
    profiles_moved: int
    profiles_merged: int


def _lock_merge_rows(
    db: Session, source_guest_id: int, target_guest_id: int
) -> tuple[Guest, Guest]:
    """Lock source, target chain and the source's tombstones; return (source, live target).

    Re-reads under the locks until nothing new turned up: a source merged away meanwhile is
    refused, a target merged away meanwhile is followed to its survivor (#951).
    """
    wanted = {source_guest_id, target_guest_id}
    for _ in range(LOCK_RETRIES):
        locked = lock_guests(db, wanted)
        source = locked.get(source_guest_id)
        if source is None or source.merged_into_guest_id is not None:
            raise ValueError("source guest is missing or already merged")
        target = _live_target(locked, target_guest_id)
        tombstones = _tombstone_ids(db, source_guest_id)
        if isinstance(target, Guest) and tombstones <= wanted:
            if target.id == source_guest_id:
                raise ValueError("target guest chain leads back to the source")
            return source, target
        wanted |= tombstones | ({target} if isinstance(target, int) else set())
    raise ValueError("guest rows kept changing while locking them for the merge")


def _live_target(locked: dict[int, Guest], guest_id: int) -> Guest | int:
    """Follow merged_into within the locked rows; the live Guest, or the id still to lock."""
    for _ in range(MAX_MERGE_HOPS):
        guest = locked.get(guest_id)
        if guest is None:
            return guest_id
        if guest.merged_into_guest_id is None:
            return guest
        guest_id = guest.merged_into_guest_id
    raise ValueError("target guest chain is too deep")


def _tombstone_ids(db: Session, guest_id: int) -> set[int]:
    rows = db.query(Guest.id).filter(Guest.merged_into_guest_id == guest_id)
    return {row_id for (row_id,) in rows}


def _target_voted_request_ids(
    db: Session, target_guest_id: int, source_votes: list[RequestVote]
) -> set[int]:
    """The requests among the source's votes that the target has already voted on."""
    if not source_votes:
        return set()
    request_ids = {vote.request_id for vote in source_votes}
    rows = db.query(RequestVote.request_id).filter(
        RequestVote.guest_id == target_guest_id, RequestVote.request_id.in_(request_ids)
    )
    return {request_id for (request_id,) in rows}


def _target_profiles_by_event(
    db: Session, target_guest_id: int, source_profiles: list[GuestProfile]
) -> dict[int, GuestProfile]:
    """The target's profiles for the events the source has profiles in, keyed by event."""
    if not source_profiles:
        return {}
    event_ids = {profile.event_id for profile in source_profiles}
    target_profiles = (
        db.query(GuestProfile)
        .filter(GuestProfile.guest_id == target_guest_id, GuestProfile.event_id.in_(event_ids))
        .all()
    )
    return {profile.event_id: profile for profile in target_profiles}


def merge_guests(db: Session, *, source_guest_id: int, target_guest_id: int) -> MergeResult:
    """Merge source Guest into target Guest.

    The source row is kept as a forwarding tombstone (PII and fingerprint cleared) so a
    stale cookie still resolves to the target (#932).
    """
    if source_guest_id == target_guest_id:
        raise ValueError("guest merge needs two different guests")
    requests_moved = 0
    votes_moved = 0
    votes_deduped = 0
    profiles_moved = 0
    profiles_merged = 0

    # Step 0: Lock the rows and settle them under the locks (#951): the source must still be
    # live, the target is followed to its live survivor, and the source's own tombstones are
    # locked too so the flattening below never waits on a row someone else holds.
    source_guest, target_guest = _lock_merge_rows(db, source_guest_id, target_guest_id)
    target_guest_id = target_guest.id

    # Step 1: Reassign requests
    req_count = (
        db.query(Request)
        .filter(Request.guest_id == source_guest_id)
        .update({Request.guest_id: target_guest_id}, synchronize_session="fetch")
    )
    requests_moved = req_count

    # Step 2: Reassign votes (with dedup)
    source_votes = db.query(RequestVote).filter(RequestVote.guest_id == source_guest_id).all()
    target_voted_request_ids = _target_voted_request_ids(db, target_guest_id, source_votes)
    for vote in source_votes:
        if vote.request_id in target_voted_request_ids:
            db.delete(vote)
            db.execute(
                update(Request)
                .where(Request.id == vote.request_id)
                .values(
                    vote_count=case(
                        (Request.vote_count > 0, Request.vote_count - 1),
                        else_=0,
                    )
                )
            )
            votes_deduped += 1
        else:
            vote.guest_id = target_guest_id
            target_voted_request_ids.add(vote.request_id)
            votes_moved += 1

    # Step 3: Reassign guest profiles (with merge)
    source_profiles = db.query(GuestProfile).filter(GuestProfile.guest_id == source_guest_id).all()
    target_profiles_by_event = _target_profiles_by_event(db, target_guest_id, source_profiles)
    for profile in source_profiles:
        target_profile = target_profiles_by_event.get(profile.event_id)
        if target_profile:
            target_profile.submission_count += profile.submission_count
            if not target_profile.nickname and profile.nickname:
                # Null out source nickname first to avoid a transient uniqueness
                # violation on the case-insensitive index before the source row is
                # deleted within the same transaction.
                source_nick = profile.nickname
                profile.nickname = None
                db.flush()
                target_profile.nickname = source_nick
            db.delete(profile)
            profiles_merged += 1
        else:
            profile.guest_id = target_guest_id
            profiles_moved += 1

    # Step 4: Turn the source into a forwarding tombstone and keep chains one hop deep
    db.execute(
        update(Guest)
        .where(Guest.merged_into_guest_id == source_guest_id)
        .values(merged_into_guest_id=target_guest_id)
    )
    source_guest.merged_into_guest_id = target_guest_id
    source_guest.merged_at = utcnow()
    source_guest.fingerprint_hash = None
    source_guest.fingerprint_components = None
    source_guest.user_agent = None
    source_guest.verified_email = None
    source_guest.email_hash = None
    source_guest.nickname = None
    source_guest.email_verified_at = None
    source_guest.human_verified_at = None
    source_guest.human_verify_count = 0

    db.commit()

    return MergeResult(
        source_guest_id=source_guest_id,
        target_guest_id=target_guest_id,
        requests_moved=requests_moved,
        votes_moved=votes_moved,
        votes_deduped=votes_deduped,
        profiles_moved=profiles_moved,
        profiles_merged=profiles_merged,
    )
