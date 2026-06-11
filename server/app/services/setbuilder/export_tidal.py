"""Tidal setlist export (issue #396).

Follows the sync-adapter precedent (services/sync/tidal_adapter.py): the
DJ's existing Tidal OAuth session, fuzzy scoring (title*0.7 + artist*0.3,
threshold 0.5) with unwanted-version filtering, and one batched
add_tracks_to_playlist call.

Resolution cascade per track: namespaced ``tidal:`` id → ISRC exact lookup
→ fuzzy search. Unresolved tracks are returned to the caller — the API
layer interrupts the export (409) unless the DJ explicitly skips them.

Each export creates a *fresh* playlist ("WrzDJ Set: <name>") and stores its
id on the set: reusing an old playlist risks clobbering DJ edits, and
appending to one breaks setlist order.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.set import Set
from app.models.user import User
from app.services import tidal as tidal_service
from app.services.setbuilder.export_common import ExportTrack
from app.services.track_normalizer import fuzzy_match_score
from app.services.version_filter import is_unwanted_version

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 0.5
PLAYLIST_DESCRIPTION = "Exported from WrzDJ Set Builder"


class TidalNotConnected(Exception):
    """The DJ has no usable Tidal session."""


class TidalExportError(Exception):
    """Tidal API failure while creating or filling the playlist."""


@dataclass(frozen=True)
class TidalExportOutcome:
    playlist_id: str
    playlist_url: str
    added: int


def _fuzzy_resolve(db: Session, user: User, track: ExportTrack) -> str | None:
    candidates = tidal_service.search_tidal_tracks(
        db, user, f"{track.artist} {track.title}", limit=10
    )
    best_id: str | None = None
    best_score = 0.0
    for candidate in candidates:
        if is_unwanted_version(candidate.title):
            continue
        score = (
            fuzzy_match_score(track.title, candidate.title) * 0.7
            + fuzzy_match_score(track.artist, candidate.artist) * 0.3
        )
        if score > best_score and score >= MATCH_THRESHOLD:
            best_score = score
            best_id = candidate.track_id
    return best_id


def resolve_for_tidal(
    db: Session, user: User, tracks: list[ExportTrack]
) -> tuple[list[tuple[ExportTrack, str]], list[ExportTrack]]:
    """Split tracks into (track, tidal_id) matches and unresolved tracks."""
    resolved: list[tuple[ExportTrack, str]] = []
    unresolved: list[ExportTrack] = []
    for track in tracks:
        if track.tidal_id:
            resolved.append((track, track.tidal_id))
            continue
        if not track.has_metadata:
            unresolved.append(track)
            continue
        if track.isrc:
            hit = tidal_service.search_tidal_by_isrc(db, user, track.isrc)
            if hit is not None:
                resolved.append((track, hit.track_id))
                continue
        match_id = _fuzzy_resolve(db, user, track)
        if match_id is not None:
            resolved.append((track, match_id))
        else:
            unresolved.append(track)
    return resolved, unresolved


def export_to_tidal(
    db: Session,
    user: User,
    set_obj: Set,
    resolved: list[tuple[ExportTrack, str]],
) -> TidalExportOutcome:
    """Create a fresh Tidal playlist, batch-add tracks, mark the set exported."""
    session = tidal_service.get_tidal_session(db, user)
    if session is None:
        raise TidalNotConnected

    try:
        playlist = session.user.create_playlist(f"WrzDJ Set: {set_obj.name}", PLAYLIST_DESCRIPTION)
        playlist_id = str(playlist.id)
    except Exception as e:  # tidalapi raises broad exceptions
        logger.error("Tidal playlist creation failed: %s: %s", type(e).__name__, e)
        raise TidalExportError("Couldn't create the Tidal playlist") from e

    track_ids = [tid for _, tid in resolved]
    if not tidal_service.add_tracks_to_playlist(db, user, playlist_id, track_ids):
        raise TidalExportError("Couldn't add tracks to the Tidal playlist")

    set_obj.tidal_playlist_id = playlist_id
    set_obj.exported_at = utcnow()
    set_obj.status = "exported"
    db.commit()

    logger.info("Exported set %s to Tidal playlist %s", set_obj.id, playlist_id)
    return TidalExportOutcome(
        playlist_id=playlist_id,
        playlist_url=f"https://tidal.com/browse/playlist/{playlist_id}",
        added=len(track_ids),
    )
