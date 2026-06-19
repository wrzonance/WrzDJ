"""Service for StageLinQ now-playing and play history management."""

import logging
from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

# Re-export normalizer functions for backward compatibility
from app.services.track_normalizer import (  # noqa: F401
    fuzzy_match_score,
    normalize_artist,
    normalize_track_title,
)


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


from datetime import timedelta

from app.models.event import Event
from app.models.now_playing import NowPlaying
from app.models.play_history import PlayHistory
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.spotify import _call_spotify_api

# --- Play history (previously in play_history_service.py) ---


def get_next_play_order(db: Session, event_id: int) -> int:
    """Get the next play_order value for an event's play history."""
    max_order = (
        db.query(PlayHistory.play_order)
        .filter(PlayHistory.event_id == event_id)
        .order_by(PlayHistory.play_order.desc())
        .first()
    )
    return (max_order[0] + 1) if max_order else 1


def archive_to_history(db: Session, now_playing: NowPlaying) -> PlayHistory:
    """Archive current now_playing to play_history."""
    history_entry = PlayHistory(
        event_id=now_playing.event_id,
        title=now_playing.title,
        artist=now_playing.artist,
        album=now_playing.album,
        deck=now_playing.deck,
        spotify_track_id=now_playing.spotify_track_id,
        album_art_url=now_playing.album_art_url,
        spotify_uri=now_playing.spotify_uri,
        matched_request_id=now_playing.matched_request_id,
        source=now_playing.source,
        started_at=now_playing.started_at,
        ended_at=utcnow(),
        play_order=get_next_play_order(db, now_playing.event_id),
    )
    db.add(history_entry)
    return history_entry


def get_play_history(
    db: Session, event_id: int, limit: int = 20, offset: int = 0
) -> tuple[list[PlayHistory], int]:
    """Get play history for an event, newest first."""
    query = db.query(PlayHistory).filter(PlayHistory.event_id == event_id)
    total = query.count()
    items = query.order_by(PlayHistory.play_order.desc()).offset(offset).limit(limit).all()
    return items, total


# Default auto-hide timeout: 10 minutes of no activity
# (track change or manual show).
# Can be overridden per-event via event.now_playing_auto_hide_minutes
NOW_PLAYING_AUTO_HIDE_MINUTES = 10

logger = logging.getLogger(__name__)


def get_event_by_code_for_bridge(db: Session, code: str) -> Event | None:
    """Get an event by code (regardless of expiry, for bridge use)."""
    return db.query(Event).filter(Event.code == code.upper()).first()


def get_now_playing(db: Session, event_id: int) -> NowPlaying | None:
    """Get the current now-playing track for an event."""
    return db.query(NowPlaying).filter(NowPlaying.event_id == event_id).first()


def is_now_playing_hidden(db: Session, event_id: int, auto_hide_minutes: int | None = None) -> bool:
    """
    Check if now playing should be hidden on kiosk.

    Hidden if ANY of these conditions are true:
    1. No track is playing (empty title)
    2. manual_hide_now_playing is True
    3. More than auto_hide_minutes since last activity
       (started_at or last_shown_at)

    Args:
        auto_hide_minutes: Per-event timeout override. Falls back to NOW_PLAYING_AUTO_HIDE_MINUTES.
    """
    now_playing = get_now_playing(db, event_id)

    # No now_playing record or empty track
    if not now_playing or not now_playing.title:
        return True

    # Manually hidden
    if now_playing.manual_hide_now_playing:
        return True

    # Auto-hide: check if more than N minutes since last activity.
    # Activity signals: started_at (track change), last_shown_at (DJ toggle).
    timeout = auto_hide_minutes if auto_hide_minutes is not None else NOW_PLAYING_AUTO_HIDE_MINUTES
    now = utcnow()
    last_activity = now_playing.started_at

    # Make timezone-aware if naive (SQLite doesn't preserve timezone)
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=UTC)

    if now_playing.last_shown_at:
        last_shown = now_playing.last_shown_at
        if last_shown.tzinfo is None:
            last_shown = last_shown.replace(tzinfo=UTC)
        if last_shown > last_activity:
            last_activity = last_shown

    if now - last_activity > timedelta(minutes=timeout):
        return True

    return False


def get_manual_hide_setting(db: Session, event_id: int) -> bool:
    """
    Get the DJ's manual hide/show preference (not the computed kiosk state).

    Returns the manual_hide_now_playing flag, ignoring auto-hide and track status.
    Used by the dashboard toggle to reflect the DJ's intent.
    """
    now_playing = get_now_playing(db, event_id)
    if not now_playing:
        return False
    return now_playing.manual_hide_now_playing


def set_now_playing_visibility(db: Session, event_id: int, hidden: bool) -> bool:
    """
    Set manual visibility for now playing on kiosk.

    When showing (hidden=False):
    - Set manual_hide_now_playing = False
    - Update last_shown_at to now (resets the auto-hide timer)

    When hiding (hidden=True):
    - Set manual_hide_now_playing = True

    Returns True on success, False if no now_playing record exists.
    """
    now_playing = get_now_playing(db, event_id)

    if not now_playing:
        # Create a placeholder if none exists
        now_playing = NowPlaying(
            event_id=event_id,
            title="",
            artist="",
            manual_hide_now_playing=hidden,
            last_shown_at=utcnow() if not hidden else None,
        )
        db.add(now_playing)
    else:
        now_playing.manual_hide_now_playing = hidden
        if not hidden:
            # When showing, reset the timer
            now_playing.last_shown_at = utcnow()

    db.commit()
    return True


def fuzzy_match_pending_request(
    db: Session, event_id: int, title: str, artist: str, threshold: float = 0.8
) -> Request | None:
    """
    Find a NEW or ACCEPTED request that fuzzy-matches the given track.

    Normalizes titles (strips generic suffixes like "Original Mix") and artists
    (canonicalizes feat/ft/featuring) before comparison so DJ equipment metadata
    differences don't prevent matches.

    Title similarity is weighted 0.7, artist 0.3 (title matters more).
    Prefers ACCEPTED over NEW at equal scores (DJ intent matters).
    Returns the best match above threshold, or None.
    """
    candidates = (
        db.query(Request)
        .filter(
            Request.event_id == event_id,
            or_(
                Request.status == RequestStatus.NEW.value,
                Request.status == RequestStatus.ACCEPTED.value,
            ),
        )
        .all()
    )

    norm_title = normalize_track_title(title)
    norm_artist = normalize_artist(artist)

    best_match = None
    best_score = 0.0

    for req in candidates:
        req_title = normalize_track_title(req.song_title)
        req_artist = normalize_artist(req.artist)

        title_score = fuzzy_match_score(req_title, norm_title)
        artist_score = fuzzy_match_score(req_artist, norm_artist)
        combined = title_score * 0.7 + artist_score * 0.3

        if combined > threshold and combined > best_score:
            best_match = req
            best_score = combined
        elif (
            combined > threshold
            and combined == best_score
            and best_match is not None
            and req.status == RequestStatus.ACCEPTED.value
            and best_match.status == RequestStatus.NEW.value
        ):
            # Prefer ACCEPTED over NEW at equal scores
            best_match = req

    if best_match:
        logger.info(
            f"Fuzzy matched '{title}' by '{artist}' to request "
            f"'{best_match.song_title}' by '{best_match.artist}' "
            f"(score: {best_score:.2f}, status: {best_match.status})"
        )

    return best_match


def lookup_spotify_album_art(title: str, artist: str) -> dict | None:
    """
    Look up album art from Spotify for a track.

    Returns dict with spotify_track_id, album_art_url, spotify_uri, or None on failure.
    """
    try:
        query = f"track:{title} artist:{artist}"
        results = _call_spotify_api(query)
        if results:
            best = results[0]
            return {
                "spotify_track_id": best.spotify_id,
                "album_art_url": best.album_art,
                "spotify_uri": f"spotify:track:{best.spotify_id}" if best.spotify_id else None,
            }
    except Exception as e:
        logger.warning(f"Spotify lookup failed for '{title}' by '{artist}': {e}")
    return None


def lookup_tidal_album_art(db: Session, owner: User, title: str, artist: str) -> str | None:
    """Look up album art from Tidal using the event owner's connected session.

    Tidal is the now-playing art's primary source: it is the app's primary search
    provider and its results carry cover art. Returns the cover URL, or None if the
    owner has no Tidal session, the track isn't found, or the lookup errors (art is
    non-critical — never let it break a now-playing update).
    """
    try:
        from app.services.tidal import search_track

        result = search_track(db, owner, artist, title)
        if result and result.cover_url:
            return result.cover_url
    except Exception as e:
        logger.warning(f"Tidal art lookup failed for '{title}' by '{artist}': {e}")
    return None


def add_manual_play(db: Session, event: Event, request: Request) -> PlayHistory:
    """
    Add a manually played song to play history.

    Called when DJ marks a request as "played" without StageLinQ.
    Idempotent: if an entry already exists for this matched_request_id, returns existing.
    """
    # Check for existing entry to ensure idempotency
    existing = (
        db.query(PlayHistory)
        .filter(
            PlayHistory.matched_request_id == request.id,
            PlayHistory.source == "manual",
        )
        .first()
    )
    if existing:
        return existing

    history_entry = PlayHistory(
        event_id=event.id,
        title=request.song_title,
        artist=request.artist,
        album=None,
        deck=None,
        spotify_track_id=None,
        album_art_url=request.artwork_url,
        spotify_uri=None,
        matched_request_id=request.id,
        source="manual",
        started_at=utcnow(),
        ended_at=utcnow(),
        play_order=get_next_play_order(db, event.id),
    )
    db.add(history_entry)
    db.commit()
    db.refresh(history_entry)
    return history_entry


def set_manual_now_playing(db: Session, event_id: int, request: Request) -> NowPlaying:
    """Upsert NowPlaying when a DJ manually marks a request as PLAYING."""
    existing = get_now_playing(db, event_id)

    if existing:
        # Archive previous track to history if it has content
        if existing.title:
            archive_to_history(db, existing)

        # Upsert track data — preserve bridge status fields
        existing.title = request.song_title
        existing.artist = request.artist
        existing.album = None
        existing.deck = None
        existing.spotify_track_id = None
        existing.album_art_url = request.artwork_url
        existing.spotify_uri = None
        existing.matched_request_id = request.id
        existing.source = "manual"
        existing.started_at = utcnow()
        existing.manual_hide_now_playing = False
        now_playing = existing
    else:
        now_playing = NowPlaying(
            event_id=event_id,
            title=request.song_title,
            artist=request.artist,
            album_art_url=request.artwork_url,
            matched_request_id=request.id,
            source="manual",
            started_at=utcnow(),
            manual_hide_now_playing=False,
        )
        db.add(now_playing)

    db.commit()
    db.refresh(now_playing)
    return now_playing


def clear_manual_now_playing(db: Session, event_id: int, request_id: int) -> None:
    """Clear NowPlaying track data when a manually-playing request is marked PLAYED.

    Only clears if source is 'manual' and matched_request_id matches — avoids
    interfering with bridge-owned NowPlaying state.
    """
    existing = get_now_playing(db, event_id)
    if not existing:
        return
    if existing.source != "manual" or existing.matched_request_id != request_id:
        return

    # Archive to history before clearing
    if existing.title:
        archive_to_history(db, existing)

    # Clear track data but preserve bridge status
    existing.title = ""
    existing.artist = ""
    existing.album = None
    existing.deck = None
    existing.spotify_track_id = None
    existing.album_art_url = None
    existing.spotify_uri = None
    existing.matched_request_id = None
    existing.started_at = utcnow()
    db.commit()


# Re-export bridge integration functions for backward compatibility
from app.services.bridge_integration import (  # noqa: E402, F401
    clear_now_playing,
    handle_now_playing_update,
    update_bridge_status,
)
