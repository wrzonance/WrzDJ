"""Tidal search and catalog adapter functions."""

from __future__ import annotations

import logging

import tidalapi
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.tidal import TidalSearchResult
from app.services.providers.tidal_account import get_tidal_session
from app.services.providers.tidal_catalog import (
    get_playlist_tracks,
    get_tidal_track_by_id,
    list_user_playlists,
    search_tidal_by_isrc,
    search_tidal_tracks,
)
from app.services.providers.tidal_results import get_artist_name, track_to_result
from app.services.track_normalizer import artist_match_score, primary_artist

logger = logging.getLogger(__name__)

__all__ = [
    "get_playlist_tracks",
    "get_tidal_track_by_id",
    "list_user_playlists",
    "search_tidal_by_isrc",
    "search_tidal_tracks",
    "search_track",
]


def search_track(
    db: Session,
    user: User,
    artist: str,
    title: str,
) -> TidalSearchResult | None:
    """Search Tidal for a track."""
    session = get_tidal_session(db, user)
    if not session:
        return None

    try:
        query = f"{primary_artist(artist)} {title}"
        results = session.search(query, models=[tidalapi.media.Track], limit=10)

        tracks = results.get("tracks", [])
        if not tracks:
            return None

        # Find best match using multi-artist-aware scoring
        title_lower = title.lower()

        for track in tracks:
            track_artist = get_artist_name(track)
            track_title = (track.name or "").lower()

            if artist_match_score(artist, track_artist) >= 0.7 and title_lower in track_title:
                return track_to_result(track)

        return track_to_result(tracks[0])

    except Exception as e:
        logger.error("Tidal track search failed (%s)", type(e).__name__)
        return None
