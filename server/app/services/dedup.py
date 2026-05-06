"""Shared deduplication service for song requests.

Single source of truth for dedupe key computation and duplicate detection.
Both the join-page (request.py) and collect (collect.py) flows import from here.
"""

import hashlib

from sqlalchemy.orm import Session

from app.models.request import Request


def compute_dedupe_key(artist: str, title: str) -> str:
    """Compute a deduplication key from normalized artist and title."""
    normalized = f"{artist.lower().strip()}:{title.lower().strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def find_duplicate(
    db: Session,
    event_id: int,
    artist: str,
    title: str,
) -> Request | None:
    """Find an existing request with the same artist+title in the event."""
    dedupe_key = compute_dedupe_key(artist, title)
    return (
        db.query(Request)
        .filter(
            Request.event_id == event_id,
            Request.dedupe_key == dedupe_key,
        )
        .first()
    )
