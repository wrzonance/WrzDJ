"""Soundcharts-backed candidate generators for the recommendation engine.

Two independent paths:

1. ``search_candidates_via_soundcharts`` — discovers songs via Soundcharts
   genre/BPM/key filters, then resolves each result to a playable Tidal track ID
   (requires a connected Tidal account).
2. ``related_candidates_from_seeds`` (#556) — seeds the paid-tier related-tracks
   endpoint from the event's existing tracks (ISRC resolved from the master
   ``tracks`` store), producing provider-agnostic candidates with NO connected
   service required. Dark by default via the adapter gate.
"""

import logging

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.recommendation.scorer import EventProfile, TrackProfile
from app.services.soundcharts import (
    RELATED_TRACKS_LIMIT,
    SoundchartsTrack,
    discover_songs,
    get_related_songs_by_isrc,
)
from app.services.tracks.store import get_track

logger = logging.getLogger(__name__)

# Max Soundcharts results to resolve via Tidal (each costs 1 Tidal search)
MAX_TIDAL_LOOKUPS = 25

# BPM range around the event average
BPM_RANGE_OFFSET = 15

# Max seed tracks to expand via the paid related endpoint (each costs API calls).
MAX_RELATED_SEEDS = 10


def search_candidates_via_soundcharts(
    db: Session,
    user: User,
    profile: EventProfile,
) -> tuple[list[TrackProfile], int]:
    """Discover tracks via Soundcharts and resolve to Tidal playable IDs.

    Returns (candidates, total_searched) where candidates are TrackProfiles
    with Tidal track_id/url, and total_searched is the number of Tidal
    lookups performed.
    """
    from app.services.tidal import search_tidal_tracks

    # Build filter parameters from the event profile
    bpm_min = None
    bpm_max = None
    if profile.avg_bpm:
        bpm_min = profile.avg_bpm - BPM_RANGE_OFFSET
        bpm_max = profile.avg_bpm + BPM_RANGE_OFFSET

    keys = list(profile.dominant_keys) if profile.dominant_keys else None
    genres = list(profile.dominant_genres)

    # Discover via Soundcharts (1 API call)
    sc_tracks = discover_songs(
        genres=genres,
        bpm_min=bpm_min,
        bpm_max=bpm_max,
        keys=keys,
        limit=MAX_TIDAL_LOOKUPS,
    )

    if not sc_tracks:
        return [], 0

    # Resolve each Soundcharts result to a Tidal track
    candidates: list[TrackProfile] = []
    total_searched = 0

    for sc_track in sc_tracks[:MAX_TIDAL_LOOKUPS]:
        query = f"{sc_track.artist} {sc_track.title}"
        results = search_tidal_tracks(db, user, query, limit=1)
        total_searched += 1

        if not results:
            continue

        tidal_result = results[0]
        # Tidal doesn't return genre — infer from the profile's dominant genre
        inferred_genre = profile.dominant_genres[0] if profile.dominant_genres else None
        candidates.append(
            TrackProfile(
                title=tidal_result.title,
                artist=tidal_result.artist,
                bpm=tidal_result.bpm,
                key=tidal_result.key,
                genre=inferred_genre,
                source="tidal",
                track_id=tidal_result.track_id,
                url=tidal_result.tidal_url,
                cover_url=tidal_result.cover_url,
                duration_seconds=tidal_result.duration_seconds,
            )
        )

    logger.info(
        "Soundcharts→Tidal resolved %d/%d tracks (searched=%d)",
        len(candidates),
        len(sc_tracks),
        total_searched,
    )
    return candidates, total_searched


def _seed_isrc(db: Session, request) -> str | None:
    """Resolve a seed request's ISRC: the request's own ISRC first, else the
    master tracks store keyed by the normalized artist+title signature."""
    if getattr(request, "isrc", None):
        return request.isrc
    # Fall back to the master store (#540/#552), the ISRC source of truth.
    from app.services.setbuilder.pool import dedupe_signature

    signature = dedupe_signature(request.artist, request.song_title)
    stored = get_track(db, signature=signature)
    return stored.isrc if stored and stored.isrc else None


def related_candidates_from_seeds(
    db: Session,
    requests: list,
    *,
    max_seeds: int = MAX_RELATED_SEEDS,
    per_seed_limit: int = RELATED_TRACKS_LIMIT,
) -> tuple[list[TrackProfile], int]:
    """Discover candidates via Soundcharts related-tracks, seeded by event ISRCs (#556).

    For each of the first ``max_seeds`` requests, resolve an ISRC (request first,
    then the master tracks store) and fetch related tracks via the dark-by-default
    adapter. Candidates are de-duplicated across seeds (by Soundcharts UUID and by
    normalized artist|title) and returned as ``TrackProfile(source="soundcharts")``
    for the shared scorer/dedup pipeline.

    Returns ``(candidates, seeds_used)`` where ``seeds_used`` counts seeds that
    resolved an ISRC and triggered a lookup. Requires NO connected music service;
    contributes nothing when the adapter is disabled/unconfigured (it returns []).
    """
    candidates: list[TrackProfile] = []
    seeds_used = 0
    seen_uuids: set[str] = set()
    seen_names: set[str] = set()

    for request in requests[:max_seeds]:
        isrc = _seed_isrc(db, request)
        if not isrc:
            continue
        seeds_used += 1
        related: list[SoundchartsTrack] = get_related_songs_by_isrc(isrc, limit=per_seed_limit)
        for track in related:
            name_key = f"{track.artist.lower().strip()}|{track.title.lower().strip()}"
            if track.soundcharts_uuid in seen_uuids or name_key in seen_names:
                continue
            seen_uuids.add(track.soundcharts_uuid)
            seen_names.add(name_key)
            candidates.append(
                TrackProfile(
                    title=track.title,
                    artist=track.artist,
                    source="soundcharts",
                )
            )

    logger.info(
        "Soundcharts related-tracks: %d candidates from %d seed(s)",
        len(candidates),
        seeds_used,
    )
    return candidates, seeds_used
