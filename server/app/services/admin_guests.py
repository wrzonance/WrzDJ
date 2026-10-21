"""Admin-side guest management: listing, editing, and deleting guest identities (#862).

Spec: docs/superpowers/specs/2026-10-21-admin-guest-management-design.md
"""

from collections import defaultdict

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_profile import GuestProfile
from app.models.request import Request
from app.schemas.admin_guest import GuestFilter
from app.services.guests.identity import browser_label

FINGERPRINT_SHORT_LEN = 12
_LIKE_ESCAPE = "\\"


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
