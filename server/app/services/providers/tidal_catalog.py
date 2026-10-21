"""Tidal playlist and track catalog lookups."""

import logging
from dataclasses import dataclass

import tidalapi
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.tidal import TidalSearchResult
from app.services.providers.tidal_account import get_tidal_session
from app.services.providers.tidal_results import track_to_result

logger = logging.getLogger(__name__)


@dataclass
class TidalPlaylistInfo:
    """Tidal playlist metadata."""

    id: str
    name: str
    num_tracks: int
    description: str | None = None
    cover_url: str | None = None
    source: str = "tidal"


class TidalFetchError(Exception):
    """Raised when Tidal playlist tracks can't be fetched (vs. genuinely empty).

    Callers that auto-reject based on track membership MUST distinguish "API
    failed" from "playlist is empty" — silently returning [] on failure leads
    to mass false-positive rejections (see ELZ2G2 incident 2026-05-19/20).
    """


def list_user_playlists(db: Session, user: User) -> list[TidalPlaylistInfo]:
    """List all playlists owned by the user on Tidal."""
    session = get_tidal_session(db, user)
    if not session:
        return []

    try:
        result = []
        for playlist in session.user.playlists():
            try:
                cover_url = playlist.image(480)
            except Exception:
                cover_url = None
            result.append(
                TidalPlaylistInfo(
                    id=str(playlist.id),
                    name=playlist.name or "",
                    num_tracks=playlist.num_tracks or 0,
                    description=playlist.description,
                    cover_url=cover_url,
                )
            )
        return result
    except Exception as exc:
        logger.error("Failed to list Tidal playlists (%s)", type(exc).__name__)
        return []


def get_playlist_tracks(db: Session, user: User, playlist_id: str) -> list[TidalSearchResult]:
    """Fetch every playlist page or raise, so API failure isn't read as empty."""
    session = get_tidal_session(db, user)
    if not session:
        raise TidalFetchError("No active Tidal session for user")

    try:
        playlist = session.playlist(playlist_id)
        tracks = []
        offset = 0
        page_size = 100
        while True:
            page = playlist.tracks(limit=page_size, offset=offset)
            if not page:
                break
            tracks.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return [track_to_result(track) for track in tracks]
    except Exception as exc:
        logger.error(
            "Tidal playlist fetch failed for playlist %s (%s)",
            playlist_id.replace("\r", " ").replace("\n", " "),
            type(exc).__name__,
        )
        raise TidalFetchError(f"Tidal playlist fetch failed ({type(exc).__name__})") from exc


def search_tidal_by_isrc(db: Session, user: User, isrc: str) -> TidalSearchResult | None:
    """Look up a Tidal track by ISRC (exact match, no fuzzy needed)."""
    session = get_tidal_session(db, user)
    if not session:
        return None
    try:
        tracks = session.get_tracks_by_isrc(isrc)
        return track_to_result(tracks[0]) if tracks else None
    except Exception as exc:
        logger.error(
            "Tidal ISRC lookup failed for %s: %s",
            isrc.replace("\r", " ").replace("\n", " "),
            type(exc).__name__,
        )
        return None


def get_tidal_track_by_id(db: Session, user: User, track_id: str) -> TidalSearchResult | None:
    """Fetch a single Tidal track by its ID (direct lookup, no search)."""
    session = get_tidal_session(db, user)
    if not session:
        return None
    try:
        track = session.track(int(track_id))
        return track_to_result(track) if track else None
    except Exception as exc:
        logger.error(
            "Tidal track fetch failed for %s: %s",
            track_id.replace("\r", " ").replace("\n", " "),
            type(exc).__name__,
        )
        return None


def search_tidal_tracks(
    db: Session,
    user: User,
    query: str,
    limit: int = 10,
) -> list[TidalSearchResult]:
    """Search Tidal for tracks."""
    session = get_tidal_session(db, user)
    if not session:
        return []
    try:
        results = session.search(query, models=[tidalapi.media.Track], limit=limit)
        return [track_to_result(track) for track in results.get("tracks", [])]
    except Exception as exc:
        logger.error("Tidal search failed (%s)", type(exc).__name__)
        return []
