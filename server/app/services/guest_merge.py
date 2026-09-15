"""Guest merge service — consolidates two Guest records into one."""

from dataclasses import dataclass

from sqlalchemy import case, update
from sqlalchemy.orm import Session

from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.request import Request
from app.models.request_vote import RequestVote


@dataclass
class MergeResult:
    source_guest_id: int
    target_guest_id: int
    requests_moved: int
    votes_moved: int
    votes_deduped: int
    profiles_moved: int
    profiles_merged: int


def merge_guests(db: Session, *, source_guest_id: int, target_guest_id: int) -> MergeResult:
    """Merge source Guest into target Guest. Source is deleted after."""
    requests_moved = 0
    votes_moved = 0
    votes_deduped = 0
    profiles_moved = 0
    profiles_merged = 0

    # Step 1: Reassign requests
    req_count = (
        db.query(Request)
        .filter(Request.guest_id == source_guest_id)
        .update({Request.guest_id: target_guest_id}, synchronize_session="fetch")
    )
    requests_moved = req_count

    # Step 2: Reassign votes (with dedup)
    source_votes = db.query(RequestVote).filter(RequestVote.guest_id == source_guest_id).all()
    for vote in source_votes:
        existing_target_vote = (
            db.query(RequestVote)
            .filter(
                RequestVote.request_id == vote.request_id,
                RequestVote.guest_id == target_guest_id,
            )
            .first()
        )
        if existing_target_vote:
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
            votes_moved += 1

    # Step 3: Reassign guest profiles (with merge)
    source_profiles = db.query(GuestProfile).filter(GuestProfile.guest_id == source_guest_id).all()
    for profile in source_profiles:
        target_profile = (
            db.query(GuestProfile)
            .filter(
                GuestProfile.event_id == profile.event_id,
                GuestProfile.guest_id == target_guest_id,
            )
            .first()
        )
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

    # Step 4: Delete source Guest
    source_guest = db.query(Guest).filter(Guest.id == source_guest_id).first()
    if source_guest:
        db.delete(source_guest)

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
