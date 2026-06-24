"""Read/write service for the master tracks table (#540)."""

from sqlalchemy.orm import Session

from app.models.track import Track
from app.services.track_normalizer import normalize_isrc


def get_track(
    db: Session, *, isrc: str | None = None, signature: str | None = None
) -> Track | None:
    """Look up a track ISRC-first, then by signature.

    Args:
        db: SQLAlchemy session
        isrc: ISRC to search (optional; will be normalized)
        signature: Signature to fall back to (optional)

    Returns:
        Track if found, None otherwise. ISRC takes precedence over signature.
    """
    norm = normalize_isrc(isrc)
    if norm:
        found = db.query(Track).filter(Track.isrc == norm).first()
        if found:
            return found
    if signature:
        return db.query(Track).filter(Track.signature == signature).first()
    return None
