"""Read/write service for the master tracks table (#540)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.track import Track
from app.services.track_normalizer import normalize_isrc
from app.services.tracks.provenance import KNOWN_SOURCES, FieldProvenance, should_overwrite


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
    entry. Inputs are validated before any mutation — ValueError is raised (with
    no DB write) if sources keys don't cover all values keys, or if any source
    name is unknown."""
    # --- Validate inputs BEFORE any DB mutation ---
    missing = set(values) - set(sources)
    if missing:
        raise ValueError(
            f"upsert_track: every values key must have a matching sources entry; "
            f"missing sources for: {sorted(missing)}"
        )
    unknown = {src for src in sources.values() if src not in KNOWN_SOURCES}
    if unknown:
        raise ValueError(
            f"upsert_track: unknown source(s) {sorted(unknown)}; "
            f"known sources are {sorted(KNOWN_SOURCES)}"
        )

    norm_isrc = normalize_isrc(identity.isrc)
    # ISRC match is authoritative; signature is only a fallback.
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

    # Backfill ISRC onto signature-matched row if it was previously missing
    if norm_isrc and not track.isrc:
        track.isrc = norm_isrc

    # Backfill soundcharts_uuid if the row was created without one
    if identity.soundcharts_uuid and not track.soundcharts_uuid:
        track.soundcharts_uuid = identity.soundcharts_uuid

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
