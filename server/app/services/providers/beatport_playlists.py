"""Beatport user playlist listing, track retrieval, and mutation."""

import logging
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.user import User
from app.schemas.beatport import BeatportSearchResult
from app.services.providers.beatport_account import ensure_beatport_token
from app.services.providers.beatport_common import (
    BEATPORT_API_BASE,
    HTTP_TIMEOUT,
    is_valid_beatport_id,
)
from app.services.providers.beatport_mapping import beatport_track_to_result

logger = logging.getLogger(__name__)


@dataclass
class BeatportPlaylistInfo:
    """Beatport playlist metadata."""

    id: str
    name: str
    num_tracks: int
    description: str | None = None
    cover_url: str | None = None
    source: str = "beatport"


def list_user_playlists(db: Session, user: User) -> list[BeatportPlaylistInfo]:
    """List user's Beatport playlists."""
    if not ensure_beatport_token(db, user):
        return []

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/my/playlists/",
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.error("Beatport playlist listing failed: %s", type(e).__name__)
        return []

    results = []
    for p in data.get("results", []):
        cover_url = None
        if p.get("image"):
            cover_url = p["image"].get("uri")
        results.append(
            BeatportPlaylistInfo(
                id=str(p.get("id", "")),
                name=p.get("name", ""),
                num_tracks=p.get("track_count", 0),
                description=p.get("description"),
                cover_url=cover_url,
            )
        )
    return results


def get_playlist_tracks(db: Session, user: User, playlist_id: str) -> list[BeatportSearchResult]:
    """Get all tracks from a Beatport playlist as BeatportSearchResult objects."""
    playlist_id = str(playlist_id)
    if not is_valid_beatport_id(playlist_id):
        logger.warning("Rejected malformed Beatport playlist id")
        return []
    validated_playlist_id = int(playlist_id)
    if not ensure_beatport_token(db, user):
        return []

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/my/playlists/{validated_playlist_id}/tracks/",
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.error("Beatport playlist tracks fetch failed: %s", type(e).__name__)
        return []

    return [
        beatport_track_to_result(entry.get("track", entry)) for entry in data.get("results", [])
    ]


def create_beatport_playlist(db: Session, user: User, event: Event) -> str | None:
    """Create a Beatport playlist for an event. Returns playlist ID or None."""
    if event.beatport_playlist_id:
        return event.beatport_playlist_id

    if not ensure_beatport_token(db, user):
        return None

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                f"{BEATPORT_API_BASE}/my/playlists/",
                json={"name": f"WrzDJ: {event.name}"},
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()

        playlist_id = str(data["id"])
        event.beatport_playlist_id = playlist_id
        db.commit()
        logger.info("Created Beatport playlist %s for event %s", playlist_id, event.code)
        return playlist_id
    except httpx.HTTPError as e:
        logger.error("Beatport playlist creation failed: %s", type(e).__name__)
        return None


def _get_playlist_track_ids(user: User, playlist_id: str) -> set[str]:
    """Fetch the set of track IDs already on a Beatport playlist."""
    playlist_id = str(playlist_id)
    if not is_valid_beatport_id(playlist_id):
        logger.warning("Rejected malformed Beatport playlist id")
        return set()
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(
                f"{BEATPORT_API_BASE}/my/playlists/{playlist_id}/tracks/",
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
            data = response.json()
        return {str(entry["track"]["id"]) for entry in data.get("results", [])}
    except (httpx.HTTPError, KeyError, TypeError) as e:
        logger.error("Beatport playlist fetch failed: %s", type(e).__name__)
        return set()


def add_track_to_beatport_playlist(
    db: Session, user: User, playlist_id: str, track_id: str
) -> bool:
    """Add a single track to a Beatport playlist. Skips if already present."""
    playlist_id, track_id = str(playlist_id), str(track_id)
    if not (is_valid_beatport_id(playlist_id) and is_valid_beatport_id(track_id)):
        logger.warning("Rejected malformed Beatport playlist or track id")
        return False
    if not ensure_beatport_token(db, user):
        return False

    existing = _get_playlist_track_ids(user, playlist_id)
    if track_id in existing:
        logger.info("Track %s already on Beatport playlist %s, skipping", track_id, playlist_id)
        return True

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                f"{BEATPORT_API_BASE}/my/playlists/{playlist_id}/tracks/",
                json={"track_id": int(track_id)},
                headers={"Authorization": f"Bearer {user.beatport_access_token}"},
            )
            response.raise_for_status()
        logger.info("Added track %s to Beatport playlist %s", track_id, playlist_id)
        return True
    except httpx.HTTPError as e:
        logger.error("Beatport add track failed: %s", type(e).__name__)
        return False


def add_tracks_to_beatport_playlist(
    db: Session, user: User, playlist_id: str, track_ids: list[str]
) -> bool:
    """Add multiple tracks to a Beatport playlist (one request per track)."""
    if not track_ids:
        return True

    return all(add_track_to_beatport_playlist(db, user, playlist_id, tid) for tid in track_ids)
