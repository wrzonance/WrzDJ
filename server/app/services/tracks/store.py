"""Read/write service for the master tracks table (#540)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.track import Track
from app.services.track_normalizer import normalize_isrc
from app.services.tracks.provenance import FieldProvenance, should_overwrite


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


@dataclass
class TrackIdentity:
    title: str
    artist: str
    signature: str
    isrc: str | None = None
    soundcharts_uuid: str | None = None


def upsert_track(
    db: Session,
    *,
    identity: TrackIdentity,
    values: dict[str, object],
    sources: dict[str, str],
    fetched_at: datetime,
) -> Track:
    """Insert or update the master row, writing each field's value + provenance
    entry. Precedence gating is added in Task 6; ISRC backfill in Task 7."""
    norm_isrc = normalize_isrc(identity.isrc)
    track = get_track(db, isrc=norm_isrc, signature=identity.signature)
    if track is None:
        track = Track(
            signature=identity.signature,
            title=identity.title,
            artist=identity.artist,
            isrc=norm_isrc,
            soundcharts_uuid=identity.soundcharts_uuid,
        )
        db.add(track)

    prov: dict = dict(track.provenance or {})
    for field, value in values.items():
        if should_overwrite(prov.get(field), sources[field]):
            setattr(track, field, value)
            prov[field] = FieldProvenance(source=sources[field], fetched_at=fetched_at).model_dump(
                mode="json"
            )
    track.provenance = prov
    db.flush()
    return track
