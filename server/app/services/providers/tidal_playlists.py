"""Tidal playlist lifecycle, mutations, and collection-removal polling."""

from __future__ import annotations

import logging

import tidalapi
from sqlalchemy.orm import Session
from tidalapi.exceptions import ObjectNotFound

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.providers.tidal_account import get_tidal_session
from app.services.providers.tidal_catalog import TidalFetchError
from app.services.providers.tidal_search import get_playlist_tracks

logger = logging.getLogger(__name__)


def _playlist_exists(session: tidalapi.Session, playlist_id: str) -> bool:
    """Return True if the Tidal playlist still exists for this session.

    Distinguishes a genuinely deleted playlist (404 → ObjectNotFound → False)
    from a transient API error (any other exception → True). We never treat a
    transient failure as "deleted", otherwise a real playlist would be orphaned
    and silently recreated on a momentary network/API blip.
    """
    try:
        session.playlist(playlist_id)
        return True
    except ObjectNotFound:
        return False
    except Exception as e:
        logger.warning(
            "Could not verify Tidal playlist %s; assuming it exists (%s)",
            playlist_id,
            type(e).__name__,
        )
        return True


def create_event_playlist(
    db: Session,
    user: User,
    event: Event,
) -> str | None:
    """Ensure a valid Tidal playlist exists for the event's accepted requests.

    Returns the stored playlist ID when it still exists on Tidal. If the stored
    playlist was deleted out-of-band (Tidal 404), the stale ID is cleared and a
    fresh playlist is created — so accepted-request sync self-heals instead of
    failing forever against a dead playlist ID.
    """
    session = get_tidal_session(db, user)
    if not session:
        # No usable session: leave any stored ID untouched (read-only callers
        # still see it); downstream sync surfaces the auth failure instead.
        return event.tidal_playlist_id

    if event.tidal_playlist_id:
        if _playlist_exists(session, event.tidal_playlist_id):
            return event.tidal_playlist_id
        logger.warning(
            "Accepted playlist %s for event %s no longer exists on Tidal; recreating",
            event.tidal_playlist_id,
            event.code,
        )
        # Clear the dead ID in memory only; the create+commit below persists the
        # recreated playlist atomically (the existing commit is already guarded,
        # so there's no separate unprotected commit that could escape the path).
        event.tidal_playlist_id = None

    playlist_name = f"WrzDJ: {event.code} – {event.name}"
    description = f"Song requests for {event.name}"
    try:
        playlist = session.user.create_playlist(playlist_name, description)
    except Exception as e:
        logger.error(
            "Failed to create Tidal playlist for event %s (%s)", event.code, type(e).__name__
        )
        return None

    event.tidal_playlist_id = str(playlist.id)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(f"Created Tidal playlist {playlist.id} for event {event.code}")
    return event.tidal_playlist_id


def ensure_collection_playlist(
    db: Session,
    user: User,
    event: Event,
) -> str | None:
    """Create (or reuse) the pre-event collection Tidal playlist for an event.

    Kept separate from create_event_playlist so collection suggestions and
    live-event accepted requests land in two distinct Tidal playlists. Like the
    accepted playlist, a stored collection playlist deleted out-of-band on Tidal
    (404) is cleared and recreated rather than failing forever.
    """
    session = get_tidal_session(db, user)
    if not session:
        return event.tidal_collection_playlist_id

    if event.tidal_collection_playlist_id:
        if _playlist_exists(session, event.tidal_collection_playlist_id):
            return event.tidal_collection_playlist_id
        logger.warning(
            "Collection playlist %s for event %s no longer exists on Tidal; recreating",
            event.tidal_collection_playlist_id,
            event.code,
        )
        # Clear the dead ID in memory only; the create+commit below persists the
        # recreated playlist atomically (the existing commit is already guarded,
        # so there's no separate unprotected commit that could escape the path).
        event.tidal_collection_playlist_id = None

    playlist_name = f"WrzDJ: {event.code} – {event.name} (pre-event)"
    description = f"Pre-event song suggestions for {event.name}"
    try:
        playlist = session.user.create_playlist(playlist_name, description)
    except Exception as e:
        logger.error(
            "Failed to create Tidal collection playlist for event %s (%s)",
            event.code,
            type(e).__name__,
        )
        return None

    event.tidal_collection_playlist_id = str(playlist.id)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(f"Created Tidal collection playlist {playlist.id} for event {event.code}")
    return event.tidal_collection_playlist_id


def add_track_to_playlist(
    db: Session,
    user: User,
    playlist_id: str,
    track_id: str,
) -> bool:
    """Add a track to a Tidal playlist."""
    return add_tracks_to_playlist(db, user, playlist_id, [track_id])


def add_tracks_to_playlist(
    db: Session,
    user: User,
    playlist_id: str,
    track_ids: list[str],
) -> bool:
    """Add multiple tracks to a Tidal playlist in one batch API call.

    Duplicates are automatically skipped by Tidal's API (allow_duplicates=False).
    """
    if not track_ids:
        return True

    session = get_tidal_session(db, user)
    if not session:
        return False

    try:
        playlist = session.playlist(playlist_id)
        playlist.add(track_ids)  # allow_duplicates=False by default → skips dupes
        logger.info(f"Added {len(track_ids)} track(s) to playlist {playlist_id}")
        return True

    except Exception as e:
        logger.error(
            "Failed to add %s track(s) to Tidal playlist %s (%s)",
            len(track_ids),
            playlist_id,
            type(e).__name__,
        )
        return False


def remove_track_from_collection_playlist(
    db: Session,
    user: User,
    event: Event,
    track_id: str,
) -> bool:
    """Remove a single track from the event's Tidal collection playlist.

    Returns True on success, False if the playlist doesn't exist or the API call fails.
    Failures are logged but not raised — removal is best-effort.
    """
    playlist_id = event.tidal_collection_playlist_id
    if not playlist_id:
        return False

    session = get_tidal_session(db, user)
    if not session:
        return False

    try:
        playlist = session.playlist(playlist_id)
        return bool(playlist.remove_by_id(track_id))
    except Exception as e:
        logger.error(
            "Failed to remove track %s from Tidal collection playlist %s (%s)",
            track_id,
            playlist_id,
            type(e).__name__,
        )
        return False


def remove_collection_tracks_batch(
    db: Session,
    user: User,
    event: Event,
    track_ids: list[str],
) -> None:
    """Remove multiple tracks from the collection playlist, one by one.

    Best-effort: logs failures per track but does not abort on error.
    """
    for track_id in track_ids:
        remove_track_from_collection_playlist(db, user, event, track_id)


def poll_tidal_collection_removals(db: Session, event: Event) -> int:
    """Detect tracks removed from the Tidal collection playlist and reject them in WrzDJ.

    Fetches current playlist contents, finds collection requests whose
    tidal_collection_track_id is no longer present, and marks them rejected.
    Only runs when the event has a collection playlist configured.

    Three safety guards prevent the mass-rejection bug from recurring:
    1. Abort on TidalFetchError (API failure is NOT 'playlist is empty').
    2. Abort if the playlist returns 0 tracks while synced rows exist.
    3. Abort if a single sweep would reject >50% of synced rows.

    Returns the count of newly rejected requests (0 on any safety abort).
    """
    from app.services.activity_log import log_activity

    if not event.tidal_collection_playlist_id:
        return 0

    user = event.created_by
    try:
        playlist_tracks = get_playlist_tracks(db, user, event.tidal_collection_playlist_id)
    except TidalFetchError as e:
        cause_type = type(e.__cause__).__name__ if e.__cause__ is not None else type(e).__name__
        logger.warning(
            "Tidal collection poll aborted for event %s (%s). NOT marking any requests rejected.",
            event.code,
            cause_type,
        )
        log_activity(
            db,
            level="warn",
            source="tidal_poll",
            message=f"Poll aborted due to Tidal fetch failure ({cause_type})",
            event_code=event.code,
        )
        return 0

    current_ids = {t.track_id for t in playlist_tracks}

    synced = (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.submitted_during_collection == True,  # noqa: E712
            Request.tidal_collection_track_id.isnot(None),
            Request.status != RequestStatus.REJECTED.value,
        )
        .all()
    )

    # Guard 2: suspicious-empty playlist
    if not current_ids and synced:
        logger.error(
            "Tidal collection poll: playlist returned 0 tracks but %d synced requests exist "
            "for event %s. Suspecting API issue, NOT rejecting.",
            len(synced),
            event.code,
        )
        log_activity(
            db,
            level="warn",
            source="tidal_poll",
            message=(f"Empty playlist with {len(synced)} synced rows; rejection sweep skipped"),
            event_code=event.code,
        )
        return 0

    candidate_rejections = [
        req for req in synced if req.tidal_collection_track_id not in current_ids
    ]

    # Guard 3: mass-rejection cap (>50% of synced rows in one sweep)
    if len(candidate_rejections) > len(synced) * 0.50 and len(candidate_rejections) > 5:
        logger.error(
            "Tidal collection poll: refused to reject %d/%d for event %s (>50%% threshold)",
            len(candidate_rejections),
            len(synced),
            event.code,
        )
        log_activity(
            db,
            level="error",
            source="tidal_poll",
            message=(
                f"Aborted mass rejection: would reject {len(candidate_rejections)}/{len(synced)}"
            ),
            event_code=event.code,
        )
        return 0

    for req in candidate_rejections:
        req.status = RequestStatus.REJECTED.value

    count = len(candidate_rejections)
    if count > 0:
        db.commit()
        rejected_ids = [r.id for r in candidate_rejections]
        logger.info("Tidal poll: rejected %d removed track(s) for event %s", count, event.code)
        log_activity(
            db,
            level="info",
            source="tidal_poll",
            message=f"Auto-rejected {count} requests (IDs: {rejected_ids[:20]})",
            event_code=event.code,
        )

    return count
