"""Auto-generated guest nicknames for frictionless-join events.

Server-side so it shares the per-event nickname uniqueness check and never
ships a wordlist to the client. Vocabulary comes from `coolname` (BSD-2-Clause,
zero deps).
"""

import secrets

from coolname import generate_slug
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.guest_profile import GuestProfile


def _slug_to_name(slug: str) -> str:
    """'dancing-panda' -> 'DancingPanda', clamped to the 30-char nickname limit."""
    name = "".join(part.capitalize() for part in slug.split("-"))
    return name[:30]


def _is_taken(db: Session, *, event_id: int, candidate: str) -> bool:
    return (
        db.query(GuestProfile.id)
        .filter(
            GuestProfile.event_id == event_id,
            func.lower(GuestProfile.nickname) == candidate.lower(),
        )
        .first()
        is not None
    )


def generate_unique_nickname(db: Session, *, event_id: int, max_attempts: int = 5) -> str:
    """Return a nickname unique (case-insensitive) within the event.

    Tries `max_attempts` two-word names, suffixing a 2-digit number after the
    first collision. Falls back to a three-word name, then to an opaque
    guaranteed-unique suffix — so an auto-generated name never collides and
    surfaces a 409 to the guest.
    """
    for attempt in range(max_attempts):
        base = _slug_to_name(generate_slug(2))
        candidate = base if attempt == 0 else f"{base}{secrets.randbelow(90) + 10}"
        candidate = candidate[:30]
        if not _is_taken(db, event_id=event_id, candidate=candidate):
            return candidate

    fallback = _slug_to_name(generate_slug(3))
    if not _is_taken(db, event_id=event_id, candidate=fallback):
        return fallback
    # Last resort: opaque, effectively-unique suffix (e.g. "Guest1a2b3c4d").
    return f"Guest{secrets.token_hex(4)}"
