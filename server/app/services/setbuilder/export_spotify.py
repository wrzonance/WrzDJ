"""Spotify WrzDJSet playlist export (issue #406)."""

import logging
import re
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.set import Set
from app.models.user import User
from app.services import spotify
from app.services.setbuilder.export_common import ExportTrack
from app.services.spotify_oauth import HTTP_TIMEOUT, refresh_access_token
from app.services.track_normalizer import fuzzy_match_score
from app.services.version_filter import is_unwanted_version

logger = logging.getLogger(__name__)

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
MATCH_THRESHOLD = 0.5
MAX_ADD_BATCH = 100
_SPOTIFY_ID_RE = re.compile(r"^[A-Za-z0-9]{1,128}$")


class SpotifyNotConnected(Exception):
    """The DJ has no usable Spotify session."""


class SpotifyExportError(Exception):
    """Spotify API failure while creating or filling the playlist."""


@dataclass(frozen=True)
class SpotifyExportOutcome:
    playlist_id: str
    playlist_url: str
    added: int


def _spotify_id(track: ExportTrack) -> str | None:
    if not track.track_id or not track.track_id.startswith("spotify:"):
        return None
    value = track.track_id.removeprefix("spotify:")
    if value.startswith("track:"):
        value = value.removeprefix("track:")
    return value if _SPOTIFY_ID_RE.fullmatch(value) else None


def _search_match(db: Session, track: ExportTrack, query: str) -> str | None:
    best_id = None
    best_score = 0.0
    for candidate in spotify.search_songs(db, query):
        if not candidate.spotify_id or is_unwanted_version(candidate.title):
            continue
        score = (
            fuzzy_match_score(track.title, candidate.title) * 0.7
            + fuzzy_match_score(track.artist, candidate.artist) * 0.3
        )
        if score > best_score and score >= MATCH_THRESHOLD:
            best_score = score
            best_id = candidate.spotify_id
    return best_id


def resolve_for_spotify(
    db: Session, user: User, tracks: list[ExportTrack]
) -> tuple[list[tuple[ExportTrack, str]], list[ExportTrack]]:
    """Split tracks into exact or searched Spotify URI matches and unresolved entries."""
    del user  # Spotify catalog search uses the app's read-only client credentials.
    resolved: list[tuple[ExportTrack, str]] = []
    unresolved: list[ExportTrack] = []
    for track in tracks:
        spotify_id = _spotify_id(track)
        if spotify_id:
            resolved.append((track, f"spotify:track:{spotify_id}"))
            continue
        if not track.has_metadata:
            unresolved.append(track)
            continue
        if track.isrc:
            exact = next(
                (
                    result.spotify_id
                    for result in spotify.search_songs(db, f"isrc:{track.isrc}")
                    if (
                        result.spotify_id
                        and result.isrc
                        and result.isrc.casefold() == track.isrc.casefold()
                    )
                ),
                None,
            )
            if exact:
                resolved.append((track, f"spotify:track:{exact}"))
                continue
        match_id = _search_match(db, track, f"{track.artist} {track.title}")
        if match_id:
            resolved.append((track, f"spotify:track:{match_id}"))
        else:
            unresolved.append(track)
    return resolved, unresolved


def _spotify_request(
    db: Session,
    user: User,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
) -> dict:
    if not refresh_access_token(db, user):
        raise SpotifyNotConnected
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.request(
                method,
                f"{SPOTIFY_API_BASE}{path}",
                headers={"Authorization": f"Bearer {user.spotify_access_token}"},
                json=json_body,
            )
            response.raise_for_status()
            return response.json() if response.content else {}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Spotify playlist API request failed: %s", type(exc).__name__)
        raise SpotifyExportError("Spotify playlist operation failed") from exc


def export_to_spotify(
    db: Session,
    user: User,
    set_obj: Set,
    resolved: list[tuple[ExportTrack, str]],
) -> SpotifyExportOutcome:
    """Create a private Spotify playlist, add all URIs in set order, and mark the set exported."""
    if not resolved:
        raise SpotifyExportError("No resolved tracks to export")
    if not user.spotify_access_token:
        raise SpotifyNotConnected

    playlist = _spotify_request(
        db,
        user,
        "POST",
        "/me/playlists",
        json_body={
            "name": f"WrzDJ Set: {set_obj.name}",
            "description": "Exported from WrzDJ Set Builder",
            "public": False,
        },
    )
    playlist_id = playlist.get("id")
    if not isinstance(playlist_id, str) or not _SPOTIFY_ID_RE.fullmatch(playlist_id):
        raise SpotifyExportError("Spotify returned an invalid playlist")

    uris = [uri for _, uri in resolved]
    for start in range(0, len(uris), MAX_ADD_BATCH):
        _spotify_request(
            db,
            user,
            "POST",
            f"/playlists/{playlist_id}/items",
            json_body={"uris": uris[start : start + MAX_ADD_BATCH]},
        )

    playlist_url = playlist.get("external_urls", {}).get("spotify")
    if not isinstance(playlist_url, str) or not playlist_url.startswith(
        "https://open.spotify.com/"
    ):
        playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"
    set_obj.spotify_playlist_id = playlist_id
    set_obj.exported_at = utcnow()
    set_obj.status = "exported"
    db.commit()
    return SpotifyExportOutcome(playlist_id=playlist_id, playlist_url=playlist_url, added=len(uris))
