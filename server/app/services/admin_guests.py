"""Admin-side guest management: listing, editing, and deleting guest identities (#862).

Spec: docs/superpowers/specs/2026-10-21-admin-guest-management-design.md
"""

from collections import defaultdict

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.email_verification_code import EmailVerificationCode
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.request import Request
from app.models.request_vote import RequestVote
from app.schemas.admin_guest import GuestFilter
from app.services.guest_identity import browser_label

FINGERPRINT_SHORT_LEN = 12
_LIKE_ESCAPE = "\\"


class ProfileNotFound(Exception):
    """The guest has no membership on that event."""


class NicknameTaken(Exception):
    """Another guest already uses that nickname (case-insensitively) in the event."""


def get_guest_by_id(db: Session, guest_id: int) -> Guest | None:
    return db.query(Guest).filter(Guest.id == guest_id).first()


def revoke_guest_email(db: Session, guest: Guest) -> Guest:
    """Forget the verified email: plaintext, lookup hash, and verification time."""
    guest.verified_email = None
    guest.email_hash = None
    guest.email_verified_at = None
    db.commit()
    db.refresh(guest)
    return guest


def update_guest_profile_nickname(
    db: Session, guest: Guest, event_id: int, nickname: str | None
) -> GuestProfile:
    """Set or clear the guest's nickname on one event.

    The case-insensitive per-event uniqueness index is Postgres-only, so the
    conflict is checked here before writing (the test DB is SQLite). Two admins
    can still both pass that check; the loser's commit then trips the index, so
    an IntegrityError is translated to the same NicknameTaken outcome.
    """
    profile = (
        db.query(GuestProfile)
        .filter(GuestProfile.guest_id == guest.id, GuestProfile.event_id == event_id)
        .first()
    )
    if profile is None:
        raise ProfileNotFound
    cleaned = (nickname or "").strip() or None
    if cleaned is not None and _nickname_taken(db, profile, cleaned):
        raise NicknameTaken
    profile.nickname = cleaned
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise NicknameTaken from exc
    db.refresh(profile)
    return profile


def _nickname_taken(db: Session, profile: GuestProfile, nickname: str) -> bool:
    return (
        db.query(GuestProfile.id)
        .filter(
            GuestProfile.event_id == profile.event_id,
            GuestProfile.id != profile.id,
            func.lower(GuestProfile.nickname) == nickname.lower(),
        )
        .first()
        is not None
    )


def delete_guest_admin(db: Session, guest: Guest) -> None:
    """Delete the identity; requests and votes stay, anonymised, in one transaction.

    `guest_id` is nulled explicitly rather than left to the FK's ON DELETE SET
    NULL so the outcome does not depend on the database enforcing it. The guest
    row is locked first: on Postgres a FOR UPDATE lock blocks the FOR KEY SHARE
    lock a concurrent request insert needs, so no request can slip in between
    the scrub and the delete and keep its nickname (SQLite ignores the lock).
    """
    db.query(Guest).filter(Guest.id == guest.id).with_for_update().one()
    db.query(Request).filter(Request.guest_id == guest.id).update(
        {"guest_id": None, "nickname": None}, synchronize_session=False
    )
    db.query(RequestVote).filter(RequestVote.guest_id == guest.id).update(
        {"guest_id": None}, synchronize_session=False
    )
    db.query(GuestProfile).filter(GuestProfile.guest_id == guest.id).delete(
        synchronize_session=False
    )
    db.query(EmailVerificationCode).filter(EmailVerificationCode.guest_id == guest.id).delete(
        synchronize_session=False
    )
    db.delete(guest)
    db.commit()


def mask_email(email: str) -> str:
    """`alice@example.com` → `a***@example.com`.

    The plaintext is encrypted at rest; the admin page only ever needs enough to
    recognise the address.
    """
    local, _, domain = email.partition("@")
    first = local[:1]
    return f"{first}***@{domain}"


def _escape_like(term: str) -> str:
    """Make `%`, `_`, and the escape char literal inside an ILIKE pattern."""
    return (
        term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


def _collision_subquery():
    """(fingerprint_hash, n) for every non-null hash; n counts guests sharing it."""
    return (
        select(Guest.fingerprint_hash.label("hash"), func.count(Guest.id).label("n"))
        .where(Guest.fingerprint_hash.is_not(None))
        .group_by(Guest.fingerprint_hash)
        .subquery()
    )


def _apply_filter(query, collisions, filter: GuestFilter):
    if filter == "verified":
        return query.filter(Guest.email_verified_at.is_not(None))
    if filter == "unverified":
        return query.filter(Guest.email_verified_at.is_(None))
    if filter == "shared":
        return query.filter(collisions.c.n > 1)
    return query


def _apply_search(query, q: str | None):
    if not q:
        return query
    pattern = f"%{_escape_like(q)}%"
    return query.filter(
        exists().where(
            GuestProfile.guest_id == Guest.id,
            GuestProfile.nickname.ilike(pattern, escape=_LIKE_ESCAPE),
        )
    )


def list_guests(
    db: Session, *, page: int, limit: int, filter: GuestFilter, q: str | None
) -> tuple[list[dict], int]:
    """Paginated guest rows for the admin page, newest activity first."""
    collisions = _collision_subquery()
    query = db.query(Guest, func.coalesce(collisions.c.n, 1)).outerjoin(
        collisions, collisions.c.hash == Guest.fingerprint_hash
    )
    query = _apply_search(_apply_filter(query, collisions, filter), q)

    total = query.count()
    rows = (
        query.order_by(Guest.last_seen_at.desc(), Guest.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    guests = [guest for guest, _n in rows]
    shared_with = {guest.id: int(n) - 1 for guest, n in rows}
    memberships = _memberships_for(db, guests)
    request_counts = _request_counts_for(db, guests)
    items = [
        _build_row(guest, shared_with[guest.id], memberships[guest.id], request_counts[guest.id])
        for guest in guests
    ]
    return items, total


def serialize_guest(db: Session, guest: Guest) -> dict:
    """One guest in the same shape `list_guests` produces (used after edits)."""
    shared = 0
    if guest.fingerprint_hash:
        shared = (
            db.query(func.count(Guest.id))
            .filter(Guest.fingerprint_hash == guest.fingerprint_hash, Guest.id != guest.id)
            .scalar()
            or 0
        )
    memberships = _memberships_for(db, [guest])[guest.id]
    request_count = _request_counts_for(db, [guest])[guest.id]
    return _build_row(guest, shared, memberships, request_count)


def _memberships_for(db: Session, guests: list[Guest]) -> dict[int, list[dict]]:
    """Event memberships per guest id, newest join first; one query for the page."""
    result: dict[int, list[dict]] = defaultdict(list)
    if not guests:
        return result
    rows = (
        db.query(GuestProfile, Event)
        .join(Event, Event.id == GuestProfile.event_id)
        .filter(GuestProfile.guest_id.in_([g.id for g in guests]))
        .order_by(GuestProfile.created_at.desc(), GuestProfile.id.desc())
        .all()
    )
    for profile, event in rows:
        result[profile.guest_id].append(
            {
                "event_id": event.id,
                "code": event.code,
                "name": event.name,
                "nickname": profile.nickname,
                "submission_count": profile.submission_count,
                "joined_at": profile.created_at,
            }
        )
    return result


def _request_counts_for(db: Session, guests: list[Guest]) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    if not guests:
        return counts
    rows = (
        db.query(Request.guest_id, func.count(Request.id))
        .filter(Request.guest_id.in_([g.id for g in guests]))
        .group_by(Request.guest_id)
        .all()
    )
    for guest_id, n in rows:
        counts[guest_id] = int(n)
    return counts


def _build_row(guest: Guest, shared_with: int, memberships: list[dict], request_count: int) -> dict:
    nickname = next((m["nickname"] for m in memberships if m["nickname"]), None)
    verified = guest.email_verified_at is not None and bool(guest.verified_email)
    return {
        "id": guest.id,
        "nickname": nickname,
        "browser": browser_label(guest.user_agent),
        "email_verified": verified,
        "email_masked": mask_email(guest.verified_email) if verified else None,
        "email_verified_at": guest.email_verified_at if verified else None,
        "human_verified_at": guest.human_verified_at,
        "human_verify_count": guest.human_verify_count or 0,
        "fingerprint_short": (
            guest.fingerprint_hash[:FINGERPRINT_SHORT_LEN] if guest.fingerprint_hash else None
        ),
        "fingerprint_shared_with": shared_with,
        "created_at": guest.created_at,
        "last_seen_at": guest.last_seen_at,
        "event_count": len(memberships),
        "request_count": request_count,
        "events": memberships,
    }
