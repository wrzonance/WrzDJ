"""Search query builders for the recommendation engine.

Generates genre-based queries for Beatport and artist-based queries
for Tidal from an EventProfile and/or template tracks.
"""

from __future__ import annotations

from app.services.recommendation.scorer import EventProfile
from app.services.track_normalizer import split_artists
from app.services.tracks.profile import TrackProfile

# Maximum number of search queries per source
MAX_SEARCH_QUERIES = 3


def build_beatport_queries(
    profile: EventProfile,
    template_tracks: list[TrackProfile] | None = None,
) -> list[str]:
    """Generate search queries for Beatport from an event profile.

    Genre-based text queries work well for Beatport (genre catalog).
    Falls back to artist names from template tracks when genres are
    unavailable (e.g., Tidal playlists).
    """
    queries = []

    # Genre-based queries (best signal)
    for genre in profile.dominant_genres[:MAX_SEARCH_QUERIES]:
        queries.append(genre)

    # If we have no genres but have template tracks, use top artists
    if not queries and template_tracks:
        artist_counts: dict[str, int] = {}
        for t in template_tracks:
            if t.artist and t.artist.lower() not in ("unknown", "various artists"):
                artist_counts[t.artist] = artist_counts.get(t.artist, 0) + 1
        # Sort by frequency, take top artists as search queries
        top_artists = sorted(artist_counts, key=lambda artist: artist_counts[artist], reverse=True)
        for artist in top_artists[:MAX_SEARCH_QUERIES]:
            queries.append(artist)

    # If we have BPM info and still have room, add a BPM-targeted query
    if profile.avg_bpm and len(queries) < MAX_SEARCH_QUERIES:
        bpm_str = str(int(profile.avg_bpm))
        if profile.dominant_genres:
            queries.append(f"{profile.dominant_genres[0]} {bpm_str} bpm")

    return queries[:MAX_SEARCH_QUERIES]


def build_tidal_queries(
    profile: EventProfile,
    requests: list | None = None,
    template_tracks: list[TrackProfile] | None = None,
) -> list[str]:
    """Generate search queries for Tidal text search.

    Limits queue-artist queries to 1 slot to prevent results dominated
    by artists already in the queue.  Remaining slots use genre-based
    discovery queries (e.g. "house music") for broader artist variety.

    Falls back to artist-only queries when no genres are available.
    """
    # Track counts by lowercase key; display_names preserves first-seen casing
    artist_counts: dict[str, int] = {}
    display_names: dict[str, str] = {}

    # Collect artists from accepted requests (split multi-artist strings)
    if requests:
        for req in requests:
            artist = getattr(req, "artist", None)
            if artist:
                for individual in split_artists(artist):
                    canonical = individual.strip()
                    key = canonical.lower()
                    if key not in ("unknown", "various artists", ""):
                        artist_counts[key] = artist_counts.get(key, 0) + 1
                        if key not in display_names:
                            display_names[key] = canonical

    # Collect artists from template tracks (split multi-artist strings)
    if template_tracks:
        for t in template_tracks:
            if t.artist:
                for individual in split_artists(t.artist):
                    canonical = individual.strip()
                    key = canonical.lower()
                    if key not in ("unknown", "various artists", ""):
                        artist_counts[key] = artist_counts.get(key, 0) + 1
                        if key not in display_names:
                            display_names[key] = canonical

    top_keys = sorted(artist_counts, key=lambda artist: artist_counts[artist], reverse=True)
    top_artists = [display_names[k] for k in top_keys]

    queries: list[str] = []

    # Slot 1: top queue artist (for "more like what's playing" results)
    if top_artists:
        queries.append(top_artists[0])

    # Slots 2-3: genre-based discovery for broader artist variety
    for genre in profile.dominant_genres[:2]:
        if len(queries) >= MAX_SEARCH_QUERIES:
            break
        queries.append(f"{genre} music")

    # Fallback: fill remaining slots with queue artists when no genres
    for artist in top_artists[1:]:
        if len(queries) >= MAX_SEARCH_QUERIES:
            break
        queries.append(artist)

    return queries[:MAX_SEARCH_QUERIES]
