"""Track metadata enrichment from Tidal and Beatport.

Enriches tracks with BPM, key, and genre by searching connected
music services. Beatport is preferred (has genre), Tidal fills gaps.
"""

import logging

import tidalapi
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.beatport import search_beatport_tracks
from app.services.recommendation.scorer import TrackProfile
from app.services.tidal import _get_artist_name, get_tidal_session
from app.services.track_match import find_best_match
from app.services.track_normalizer import (
    is_remix_title,
    primary_artist,
)

logger = logging.getLogger(__name__)

# Maximum tracks to enrich per event (limit API calls)
MAX_ENRICH_TRACKS = 30


def enrich_from_tidal(
    db: Session,
    user: User,
    title: str,
    artist: str,
) -> TrackProfile | None:
    """Search Tidal and extract BPM/key from the result.

    Uses tidalapi.Track.bpm and .audio_modes directly, which
    are not exposed by the existing _track_to_result helper.
    """
    session = get_tidal_session(db, user)
    if not session:
        return None

    try:
        query = f"{primary_artist(artist)} {title}"
        results = session.search(query, models=[tidalapi.media.Track], limit=5)
        tracks = results.get("tracks", [])
        if not tracks:
            return None

        # Find best match (prefer originals over remixes for non-remix queries).
        # Shared selector (#551): adds the artist-score floor + BPM-consensus
        # tiebreaker the old inline loop lacked. Tidal exposes .name (not .title)
        # and a custom artist accessor, so pass those through.
        best_track = find_best_match(
            tracks,
            title,
            artist,
            prefer_original=not is_remix_title(title),
            get_title=lambda t: t.name or "",
            get_artist=_get_artist_name,
            get_mix_name=lambda t: None,  # tidalapi has no mix_name — detect remixes from the title
        )
        if not best_track:
            return None

        # Extract BPM and key directly from the tidalapi Track object
        bpm = None
        key = None
        try:
            bpm = float(best_track.bpm) if hasattr(best_track, "bpm") and best_track.bpm else None
        except (TypeError, ValueError):
            pass  # nosec B110
        try:
            key = best_track.key if hasattr(best_track, "key") and best_track.key else None
        except (TypeError, AttributeError):
            pass  # nosec B110

        cover_url = None
        try:
            if best_track.album:
                cover_url = best_track.album.image(640)
        except Exception:  # nosec B110 — cover art is optional
            pass

        return TrackProfile(
            title=best_track.name or title,
            artist=_get_artist_name(best_track),
            bpm=bpm,
            key=key,
            source="tidal",
            track_id=str(best_track.id),
            url=f"https://tidal.com/browse/track/{best_track.id}",
            cover_url=cover_url,
            duration_seconds=best_track.duration if best_track.duration else None,
        )
    except Exception as e:
        logger.error("Tidal enrichment failed for '%s - %s': %s", artist, title, type(e).__name__)
        return None


def enrich_from_beatport(
    db: Session,
    user: User,
    title: str,
    artist: str,
) -> TrackProfile | None:
    """Search Beatport and extract BPM/key/genre from the result."""
    results = search_beatport_tracks(db, user, f"{primary_artist(artist)} {title}", limit=5)
    if not results:
        return None

    # Find best match (prefer originals over remixes for non-remix queries).
    # Shared selector (#551) — same scoring as the Tidal path and the request
    # enrichment pipeline. Beatport results expose the default .title/.artist/
    # .mix_name/.bpm shape, so no accessors are needed.
    best_result = find_best_match(results, title, artist, prefer_original=not is_remix_title(title))
    if not best_result:
        return None

    return TrackProfile(
        title=best_result.title,
        artist=best_result.artist,
        bpm=float(best_result.bpm) if best_result.bpm else None,
        key=best_result.key,
        genre=best_result.genre,
        source="beatport",
        track_id=best_result.track_id,
        url=best_result.beatport_url,
        cover_url=best_result.cover_url,
        duration_seconds=best_result.duration_seconds,
    )


def enrich_track(
    db: Session,
    user: User,
    title: str,
    artist: str,
) -> TrackProfile:
    """Enrich a track with metadata from connected services.

    Tries Beatport first (has genre), fills gaps from Tidal.
    Returns a TrackProfile with whatever metadata could be found.
    """
    bp_profile = None
    tidal_profile = None

    if user.beatport_access_token:
        bp_profile = enrich_from_beatport(db, user, title, artist)

    if user.tidal_access_token:
        tidal_profile = enrich_from_tidal(db, user, title, artist)

    # If both found, merge: Beatport is primary (has genre), Tidal fills gaps
    if bp_profile and tidal_profile:
        return TrackProfile(
            title=bp_profile.title,
            artist=bp_profile.artist,
            bpm=bp_profile.bpm or tidal_profile.bpm,
            key=bp_profile.key or tidal_profile.key,
            genre=bp_profile.genre,
            source="beatport",
            track_id=bp_profile.track_id,
            url=bp_profile.url,
            cover_url=bp_profile.cover_url or tidal_profile.cover_url,
            duration_seconds=bp_profile.duration_seconds or tidal_profile.duration_seconds,
        )

    if bp_profile:
        return bp_profile

    if tidal_profile:
        return tidal_profile

    # Neither service found the track — return minimal profile
    return TrackProfile(title=title, artist=artist)


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
