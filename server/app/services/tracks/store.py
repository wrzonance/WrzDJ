"""Read/write service for the master tracks table (#540)."""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.track import Track
from app.services.track_normalizer import normalize_isrc
from app.services.tracks.provenance import KNOWN_SOURCES, FieldProvenance, should_overwrite

logger = logging.getLogger(__name__)

# Columns NOT writable via the `values` dict: identity fields come from
# TrackIdentity (signature/title/artist/isrc/soundcharts_uuid) and these are
# ORM-managed (id/provenance/created_at/updated_at). `values` carries enrichment
# fields only; any other key is a caller bug and must be rejected, not silently
# set as a non-persisted instance attribute while provenance claims a write.
_NON_VALUE_FIELDS = frozenset(
    {
        "id",
        "signature",
        "title",
        "artist",
        "isrc",
        "soundcharts_uuid",
        "provenance",
        "created_at",
        "updated_at",
    }
)


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
    entry. Unresolved (None) values are dropped — a provider lacking a field must
    not overwrite an existing value, and gets no provenance entry (spec §9).
    Inputs are validated before any mutation — ValueError is raised (with no DB
    write) if a values key is not a writable column, sources keys don't cover all
    values keys, or any source name is unknown."""
    # Drop unresolved fields up front so None never overwrites stored data.
    values = {k: v for k, v in values.items() if v is not None}

    # --- Validate inputs BEFORE any DB mutation ---
    writable = {attr.key for attr in Track.__mapper__.column_attrs} - _NON_VALUE_FIELDS
    unknown_fields = set(values) - writable
    if unknown_fields:
        raise ValueError(
            f"upsert_track: unknown writable field(s) {sorted(unknown_fields)}; "
            f"allowed fields are {sorted(writable)}"
        )
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
        track = _insert_identity_reconciling(db, identity=identity, norm_isrc=norm_isrc)

    # ISRC CONFLICT — checked AFTER resolution so it covers BOTH the initial
    # get_track signature fallback AND the reconcile-race re-read inside
    # _insert_identity_reconciling (which can also land on a signature-matched row
    # for a DIFFERENT recording). The two ISRCs identify distinct recordings (same
    # normalized artist/title, different release/remaster); the signature is UNIQUE
    # so this recording cannot get its own row here. Refuse to overwrite the
    # existing row's data — the recording is simply not stored (its metadata still
    # lives on the caller's Request); this prevents corruption. Full
    # multi-recording-per-signature support is a #542 schema concern (signature is
    # the identity bottleneck, not ISRC). A freshly INSERTED row has isrc==norm_isrc,
    # so this never trips on the insert path.
    if norm_isrc and track.isrc and track.isrc != norm_isrc:
        logger.warning(
            "upsert_track: ISRC conflict on signature %s (existing isrc=%s, incoming=%s); "
            "skipping write to avoid overwriting a different recording.",
            identity.signature,
            track.isrc,
            norm_isrc,
        )
        return track

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


def _insert_identity_reconciling(
    db: Session, *, identity: TrackIdentity, norm_isrc: str | None
) -> Track:
    """Insert a new row with only its identity columns, tolerating a lost race.

    Two callers can both miss in get_track and both try to create the same new
    ISRC/signature. The first INSERT wins; the second hits uq_tracks_isrc /
    uq_tracks_signature. We materialize ONLY the bare identity INSERT inside a
    SAVEPOINT so an IntegrityError rolls back just that INSERT (not the caller's
    outer work). On conflict we re-read the row the winner committed and return
    it for the precedence-guarded value merge — net result one row, no lost
    writes (spec §5).

    Empirical note (#540): in this codebase Session.begin_nested() flushes
    pending objects while taking its snapshot, so db.add() MUST happen INSIDE the
    savepoint — otherwise the INSERT fires during begin_nested() and the
    IntegrityError escapes the try. After sp.rollback() the conflicting pending
    Track is already evicted from the session (no db.expunge() needed).
    """
    sp = db.begin_nested()
    try:
        track = Track(
            signature=identity.signature,
            title=identity.title,
            artist=identity.artist,
            isrc=norm_isrc,
            soundcharts_uuid=identity.soundcharts_uuid,
        )
        db.add(track)
        db.flush()
        sp.commit()
        return track
    except IntegrityError:
        sp.rollback()
        # A concurrent caller inserted the same identity first — reconcile by
        # re-reading the now-existing row and merging onto it.
        existing = get_track(db, isrc=norm_isrc, signature=identity.signature)
        if existing is None:
            # Genuinely unreconcilable unique violation — do not swallow it.
            raise
        return existing
