"""Template playlist conversion to TrackProfile lists.

Converts tracks from Tidal or Beatport playlists into TrackProfile
objects suitable for building an EventProfile for recommendations.
"""

import logging

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.beatport import BeatportSearchResult
from app.schemas.tidal import TidalSearchResult
from app.services.tracks.profile import TrackProfile
from app.services.tracks.profile_mappers import (
    beatport_result_to_profile,
    tidal_result_to_profile,
)

logger = logging.getLogger(__name__)

# Maximum tracks to use from a template playlist
MAX_TEMPLATE_TRACKS = 50


def tidal_get_playlist_tracks(db: Session, user: User, playlist_id: str) -> list[TidalSearchResult]:
    """Fetch provider-neutral results from a Tidal playlist."""
    from app.services.providers.tidal_search import get_playlist_tracks

    return get_playlist_tracks(db, user, playlist_id)


def beatport_get_playlist_tracks(
    db: Session, user: User, playlist_id: str
) -> list[BeatportSearchResult]:
    """Fetch BeatportSearchResult objects from a Beatport playlist."""
    from app.services.providers.beatport_playlists import get_playlist_tracks

    return get_playlist_tracks(db, user, playlist_id)


def tracks_from_tidal_playlist(db: Session, user: User, playlist_id: str) -> list[TrackProfile]:
    """Convert a Tidal playlist into a list of TrackProfile objects."""
    results = tidal_get_playlist_tracks(db, user, playlist_id)

    profiles = []
    for track in results[:MAX_TEMPLATE_TRACKS]:
        try:
            profiles.append(tidal_result_to_profile(track))
        except Exception as e:
            logger.warning("Failed to convert Tidal track: %s", e)
            continue

    return profiles


def tracks_from_beatport_playlist(db: Session, user: User, playlist_id: str) -> list[TrackProfile]:
    """Convert a Beatport playlist into a list of TrackProfile objects."""
    results = beatport_get_playlist_tracks(db, user, playlist_id)

    profiles = []
    for r in results[:MAX_TEMPLATE_TRACKS]:
        profiles.append(beatport_result_to_profile(r))

    return profiles
