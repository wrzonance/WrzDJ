"""Track metadata enrichment from Tidal and Beatport.

Enriches tracks with BPM, key, and genre by searching connected
music services. Beatport is preferred (has genre), Tidal fills gaps.
"""

import logging

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.tracks.enrichment import enrich_track
from app.services.tracks.profile import TrackProfile

logger = logging.getLogger(__name__)

# Maximum tracks to enrich per event (limit API calls)
MAX_ENRICH_TRACKS = 30


def enrich_event_tracks(
    db: Session,
    user: User,
    requests: list,
) -> list[TrackProfile]:
    """Enrich accepted/played requests with BPM/key/genre metadata.

    Uses stored metadata from the Request model (genre, bpm, musical_key)
    when available, falling back to API enrichment only for missing fields.
    Processes up to MAX_ENRICH_TRACKS most recent requests.
    """
    to_enrich = requests[:MAX_ENRICH_TRACKS]

    profiles = []
    for req in to_enrich:
        has_genre = bool(getattr(req, "genre", None))
        has_bpm = getattr(req, "bpm", None) is not None
        has_key = bool(getattr(req, "musical_key", None))

        if has_genre and has_bpm and has_key:
            # All metadata present — skip API enrichment entirely
            profiles.append(
                TrackProfile(
                    title=req.song_title,
                    artist=req.artist,
                    bpm=float(req.bpm),
                    key=req.musical_key,
                    genre=req.genre,
                )
            )
        elif has_genre or has_bpm or has_key:
            # Partial metadata — enrich only missing fields via API
            api_profile = enrich_track(db, user, req.song_title, req.artist)
            profiles.append(
                TrackProfile(
                    title=req.song_title,
                    artist=req.artist,
                    bpm=float(req.bpm) if has_bpm else api_profile.bpm,
                    key=req.musical_key if has_key else api_profile.key,
                    genre=req.genre if has_genre else api_profile.genre,
                    source=api_profile.source,
                    track_id=api_profile.track_id,
                    url=api_profile.url,
                    cover_url=api_profile.cover_url,
                    duration_seconds=api_profile.duration_seconds,
                )
            )
        else:
            # No stored metadata — full API enrichment
            profiles.append(enrich_track(db, user, req.song_title, req.artist))

    return profiles
