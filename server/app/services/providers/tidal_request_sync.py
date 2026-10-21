"""Tidal synchronization of collection and accepted requests."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, TidalSyncStatus
from app.models.user import User
from app.schemas.tidal import TidalSyncResult
from app.services.providers.tidal_playlists import (
    add_track_to_playlist,
    add_tracks_to_playlist,
    create_event_playlist,
    ensure_collection_playlist,
)
from app.services.providers.tidal_search import search_tidal_tracks, search_track
from app.services.sync.base import SyncStatus

logger = logging.getLogger(__name__)


def sync_collection_requests_batch(
    db: Session,
    user: User,
    event: Event,
    requests: list[Request],
) -> None:
    """Batch-sync pre-event collection requests to the collection playlist.

    Searches tracks sequentially, adds all found IDs in one API call, and
    stores the matched Tidal track ID on each request for bidirectional sync.
    Tidal's allow_duplicates=False deduplicates silently at the API layer.
    """
    if not requests:
        return

    playlist_id = ensure_collection_playlist(db, user, event)
    if not playlist_id:
        return

    track_ids: list[str] = []
    matched: list[tuple[Request, str]] = []  # (request, track_id)
    for req in requests:
        try:
            results = search_tidal_tracks(db, user, f"{req.song_title} {req.artist}")
            if results:
                track_id = results[0].track_id
                track_ids.append(track_id)
                matched.append((req, track_id))
        except Exception as e:
            logger.error(
                "Collection sync search failed for request %s (%s)",
                req.id,
                type(e).__name__,
            )

    if track_ids:
        if add_tracks_to_playlist(db, user, playlist_id, track_ids):
            for req, track_id in matched:
                req.tidal_collection_track_id = track_id
            db.commit()


def _record_tidal_sync_result(
    request: Request,
    status: SyncStatus,
    *,
    url: str | None = None,
    track_id: str | None = None,
    error: str | None = None,
) -> None:
    """Upsert this request's Tidal entry in sync_results_json.

    The dashboard badge renders from sync_results_json. The multi-service
    orchestrator writes it on auto-sync; the manual retry path (sync_request_to_tidal)
    must do the same, or a retry that actually succeeds never turns the chip green.
    Uses the same status vocabulary ("added"/"not_found"/"error") so both paths
    render identically.
    """
    try:
        entries = json.loads(request.sync_results_json) if request.sync_results_json else []
        if not isinstance(entries, list):
            entries = []
    except (json.JSONDecodeError, TypeError):
        entries = []

    entries = [e for e in entries if isinstance(e, dict) and e.get("service") != "tidal"]
    entries.append(
        {
            "service": "tidal",
            "status": status.value,
            "url": url,
            "track_id": track_id,
            "error": error,
        }
    )
    request.sync_results_json = json.dumps(entries)


def sync_request_to_tidal(
    db: Session,
    request: Request,
) -> TidalSyncResult:
    """Sync an accepted request to Tidal playlist."""
    event = request.event
    user = event.created_by

    if not event.tidal_sync_enabled:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Tidal sync not enabled for this event",
        )

    if not user.tidal_access_token:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Tidal account not linked",
        )

    playlist_id = create_event_playlist(db, user, event)
    if not playlist_id:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Failed to create Tidal playlist",
        )

    track = search_track(db, user, request.artist, request.song_title)
    if not track:
        _record_tidal_sync_result(request, SyncStatus.NOT_FOUND, error="Track not found on Tidal")
        db.commit()
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.NOT_FOUND,
            error="Track not found on Tidal",
        )

    if add_track_to_playlist(db, user, playlist_id, track.track_id):
        _record_tidal_sync_result(
            request, SyncStatus.ADDED, url=track.tidal_url, track_id=track.track_id
        )
        db.commit()
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.SYNCED,
            tidal_track_id=track.track_id,
        )
    else:
        _record_tidal_sync_result(
            request, SyncStatus.ERROR, error="Failed to add track to playlist"
        )
        db.commit()
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Failed to add track to playlist",
        )


def manual_link_track(
    db: Session,
    request: Request,
    tidal_track_id: str,
) -> TidalSyncResult:
    """Manually link a Tidal track to a request."""
    event = request.event
    user = event.created_by

    if not user.tidal_access_token:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Tidal account not linked",
        )

    playlist_id = event.tidal_playlist_id
    if not playlist_id:
        playlist_id = create_event_playlist(db, user, event)
        if not playlist_id:
            return TidalSyncResult(
                request_id=request.id,
                status=TidalSyncStatus.ERROR,
                error="Failed to create Tidal playlist",
            )

    if add_track_to_playlist(db, user, playlist_id, tidal_track_id):
        db.commit()
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.SYNCED,
            tidal_track_id=tidal_track_id,
        )
    else:
        return TidalSyncResult(
            request_id=request.id,
            status=TidalSyncStatus.ERROR,
            error="Failed to add track to playlist",
        )
