"""Bridge integration — now-playing updates + admin command queue."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.now_playing import NowPlaying
from app.models.request import Request, RequestStatus

# `archive_to_history` is imported lazily inside the handlers below to avoid a
# circular import with now_playing.py, which re-exports the bridge update
# helpers at module bottom (legacy compatibility shim).

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


# --- Admin command queue (previously in services/bridge_commands.py) ---
# Thread-safe in-memory command queue polled by the bridge on its next cycle.

_COMMAND_TTL_SECONDS = 60
_commands: dict[str, list[dict]] = {}
_lock = threading.Lock()


def queue_command(event_code: str, command_type: str, payload: dict[str, Any] | None = None) -> str:
    """Queue a command for the bridge to pick up. Returns the UUID command_id."""
    command_id = str(uuid.uuid4())
    entry = {
        "id": command_id,
        "type": command_type,
        "payload": payload or {},
        "created_at": utcnow(),
    }
    with _lock:
        if event_code not in _commands:
            _commands[event_code] = []
        _commands[event_code].append(entry)
    return command_id


def poll_commands(event_code: str) -> list[dict]:
    """Return and atomically clear all pending commands for an event.

    Expired commands (older than TTL) are pruned before returning.
    """
    now = utcnow()
    with _lock:
        pending = _commands.pop(event_code, [])

    return [
        cmd for cmd in pending if (now - cmd["created_at"]).total_seconds() <= _COMMAND_TTL_SECONDS
    ]


def clear_all() -> None:
    """Clear the entire command store. Used for testing."""
    with _lock:
        _commands.clear()


def handle_now_playing_update(
    db: Session,
    event_code: str,
    title: str,
    artist: str,
    album: str | None = None,
    deck: str | None = None,
    source: str | None = None,
) -> NowPlaying | None:
    """Handle a new track from the bridge.

    Flow:
    1. Resolve fuzzy match + album art (read-only / external) BEFORE staging writes
    2. Archive previous track to play_history (if exists)
    3. Transition previously-playing requests "playing" -> "played"
    4. Upsert now_playing with the new track + resolved art
    5. Link the fuzzy-matched request -> "playing"
    """
    from app.services.now_playing import (
        archive_to_history,
        fuzzy_match_pending_request,
        get_event_by_code_for_bridge,
        get_now_playing,
        lookup_spotify_album_art,
        lookup_tidal_album_art,
    )

    event = get_event_by_code_for_bridge(db, event_code)
    if not event:
        logger.warning(f"Event not found for code: {event_code}")
        return None

    # Resolve the match and album art BEFORE staging any DB writes.
    # lookup_tidal_album_art can refresh the owner's Tidal OAuth token, which
    # commits the session; doing it here — while nothing of ours is staged —
    # keeps that refresh from prematurely committing this handler's bridge
    # mutations, which are committed together at the end.
    matched_request = fuzzy_match_pending_request(db, event.id, title, artist)

    # Album-art precedence: the matched request's already-resolved art (guest
    # search is Tidal-primary) -> a fresh Tidal lookup via the owner's session ->
    # Spotify as a last resort. Spotify is no longer primary: its app-level search
    # 403s when the owner account lacks Premium, which silently blanked now-playing
    # art while Tidal-backed queue art kept working.
    album_art_url: str | None = None
    spotify_track_id: str | None = None
    spotify_uri: str | None = None
    if matched_request and matched_request.artwork_url:
        album_art_url = matched_request.artwork_url
    else:
        album_art_url = lookup_tidal_album_art(db, event.created_by, title, artist)
        if not album_art_url:
            spotify_data = lookup_spotify_album_art(title, artist)
            if spotify_data:
                spotify_track_id = spotify_data["spotify_track_id"]
                album_art_url = spotify_data["album_art_url"]
                spotify_uri = spotify_data["spotify_uri"]

    # Step 1: Archive previous track if exists
    existing = get_now_playing(db, event.id)
    if existing and existing.title:
        archive_to_history(db, existing)

    # Step 2: Transition ALL playing requests for this event to played
    # (handles both bridge-matched and manually-playing requests)
    playing_requests = (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.status == RequestStatus.PLAYING.value,
        )
        .all()
    )
    for req in playing_requests:
        req.status = RequestStatus.PLAYED.value
        req.updated_at = _utcnow()
        logger.info(f"Marked request {req.id} as played (bridge override)")

    # Step 3: Upsert now_playing with the resolved art/IDs
    if existing:
        existing.title = title
        existing.artist = artist
        existing.album = album
        existing.deck = deck
        existing.source = source or "bridge"
        existing.started_at = _utcnow()
        existing.spotify_track_id = spotify_track_id
        existing.album_art_url = album_art_url
        existing.spotify_uri = spotify_uri
        existing.matched_request_id = None
        now_playing = existing
    else:
        now_playing = NowPlaying(
            event_id=event.id,
            title=title,
            artist=artist,
            album=album,
            deck=deck,
            source=source or "bridge",
            started_at=_utcnow(),
            spotify_track_id=spotify_track_id,
            album_art_url=album_art_url,
            spotify_uri=spotify_uri,
        )
        db.add(now_playing)

    # Step 4: Link the fuzzy-matched request as now playing
    if matched_request:
        matched_request.status = RequestStatus.PLAYING.value
        matched_request.updated_at = _utcnow()
        now_playing.matched_request_id = matched_request.id
        logger.info(f"Auto-matched request {matched_request.id} as playing")

    db.commit()
    db.refresh(now_playing)
    return now_playing


def update_bridge_status(
    db: Session,
    event_code: str,
    connected: bool,
    device_name: str | None = None,
) -> bool:
    """Update bridge connection status for an event."""
    from app.services.now_playing import get_event_by_code_for_bridge, get_now_playing

    event = get_event_by_code_for_bridge(db, event_code)
    if not event:
        return False

    now_playing = get_now_playing(db, event.id)
    if now_playing:
        now_playing.bridge_connected = connected
        now_playing.bridge_device_name = device_name
        now_playing.bridge_last_seen = _utcnow() if connected else now_playing.bridge_last_seen
    else:
        # Create a placeholder now_playing for status tracking
        now_playing = NowPlaying(
            event_id=event.id,
            title="",
            artist="",
            bridge_connected=connected,
            bridge_device_name=device_name,
            bridge_last_seen=_utcnow() if connected else None,
        )
        db.add(now_playing)

    # Log bridge connection/disconnection
    try:
        from app.services.activity_log import log_activity

        if connected:
            device_info = f" ({device_name})" if device_name else ""
            log_activity(
                db,
                "info",
                "bridge",
                f"Bridge connected{device_info}",
                event_code=event_code,
                user_id=event.created_by_user_id,
            )
        else:
            log_activity(
                db,
                "warning",
                "bridge",
                "Bridge disconnected",
                event_code=event_code,
                user_id=event.created_by_user_id,
            )
    except Exception:
        pass  # nosec B110

    db.commit()
    return True


def clear_now_playing(db: Session, event_code: str) -> bool:
    """Clear now_playing for an event (bridge disconnect or deck cleared)."""
    from app.services.now_playing import (
        archive_to_history,
        get_event_by_code_for_bridge,
        get_now_playing,
    )

    event = get_event_by_code_for_bridge(db, event_code)
    if not event:
        return False

    existing = get_now_playing(db, event.id)
    if existing and existing.title:
        archive_to_history(db, existing)

        # Mark matched request as played if exists
        if existing.matched_request_id:
            request = db.query(Request).filter(Request.id == existing.matched_request_id).first()
            if request and request.status == RequestStatus.PLAYING.value:
                request.status = RequestStatus.PLAYED.value
                request.updated_at = _utcnow()

        # Clear the now_playing fields but keep connection status
        existing.title = ""
        existing.artist = ""
        existing.album = None
        existing.deck = None
        existing.spotify_track_id = None
        existing.album_art_url = None
        existing.spotify_uri = None
        existing.matched_request_id = None
        existing.started_at = _utcnow()

        db.commit()
    return True
