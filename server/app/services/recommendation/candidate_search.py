"""Candidate filtering and provider search for recommendations."""

import logging
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.user import User
from app.services.recommendation.context import RecommendationContext
from app.services.recommendation.scorer import EventProfile
from app.services.track_normalizer import split_artists
from app.services.tracks.profile import TrackProfile
from app.services.tracks.profile_mappers import (
    beatport_result_to_profile,
    tidal_result_to_profile,
)
from app.services.version_filter import is_unwanted_version

logger = logging.getLogger(__name__)
SEARCH_LIMIT = 10

BLOCKED_GENRES = {
    "dj tools",
    "dj tool",
    "acapellas",
    "acapella",
    "acapellas/dj tools",
    "karaoke",
    "sound effects",
    "stems",
    "samples",
    "meditation",
    "sleep",
    "white noise",
    "nature recordings",
    "asmr",
    "binaural",
    "healing",
    "spa",
}


def _is_blocked_genre(genre: str | None) -> bool:
    """Check if a genre matches or contains a blocked genre keyword."""
    if not genre:
        return False
    genre_lower = genre.lower()
    if genre_lower in BLOCKED_GENRES:
        return True
    return any(blocked in genre_lower for blocked in BLOCKED_GENRES)


# Title/artist substrings that indicate non-music or utility tracks
BLOCKED_TITLE_KEYWORDS = [
    "backing track",
    "drumless",
    "drum track",
    "jam track",
    "click track",
    "no click",
    "practice track",
    "minus one",
    # Stock/royalty-free music indicators
    "music bed",
    "production music",
    "royalty free",
    "royalty-free",
    "stock music",
    "library music",
    "music for",  # "[Genre] Music for [Purpose]" = stock/library music pattern
    "cinematic music",
    "background music",
    "meditation music",
    "sleep music",
    "study music",
    # Functional/wellness music (not DJ material)
    "relaxation music",
    "healing music",
    "yoga music",
    "spa music",
    "massage music",
    "therapy music",
    "reiki music",
    # Non-music audio content
    "binaural beats",
    "white noise",
    "pink noise",
    "brown noise",
    "rain sounds",
    "ocean waves",
    "nature sounds",
    "sleep sounds",
    "asmr",
    "solfeggio",
    "isochronic",
    # Production format terms (only appear in stock/library music)
    "underscore",
    "stinger",
    "bumper",
    "audio logo",
    "jingle",
    "seamless loop",
    "music loop",
    # Practice/stripped track variants
    "play along",
    "bassless",
    "guitarless",
    "no vocals",
    "no drums",
]

# Suffixes/keywords that indicate stock music artist names
_STOCK_ARTIST_SUFFIXES = [
    " music zone",
    " music bed",
    " music group",
    " beats",
    " sounds",
    " audio",
    " productions",
    " music ensemble",
    " relax club",
    " music therapy",
    " sound effects",
    " noise machine",
    " sound library",
    " relaxation",
    " meditation",
    " sleep music",
]
_STOCK_ARTIST_KEYWORDS = [
    "brainrot",
    "royalty free",
    "royalty-free",
    "white noise for",
    "sleep sound",
    "rain sounds",
    "nature sounds",
    "lofi sleep",
    "study music",
]


def _is_stock_music_artist(artist: str) -> bool:
    """Check if an artist name matches stock/royalty-free music patterns."""
    lower = artist.lower().strip()
    return any(lower.endswith(s) for s in _STOCK_ARTIST_SUFFIXES) or any(
        kw in lower for kw in _STOCK_ARTIST_KEYWORDS
    )


def _is_junk_candidate(title: str, artist: str) -> bool:
    """Check if a candidate is a non-music utility track based on title/artist."""
    title_lower = title.lower()
    artist_lower = artist.lower()
    combined = f"{title_lower} {artist_lower}"
    return any(kw in combined for kw in BLOCKED_TITLE_KEYWORDS)


def _filter_beatport_result(r) -> bool:
    """Check if a Beatport result should be included (passes all filters)."""
    if is_unwanted_version(r.title):
        return False
    if _is_blocked_genre(r.genre):
        return False
    if _is_junk_candidate(r.title, r.artist):
        return False
    if _is_stock_music_artist(r.artist):
        return False
    return True


def _search_beatport_structured(
    db: Session,
    user: User,
    profile: EventProfile,
) -> tuple[list[TrackProfile], int]:
    """Search Beatport using structured genre/BPM/key browse.

    Falls back to text search if no genre IDs can be resolved.
    Returns (candidates, total_searched).
    """
    from app.services.providers.beatport_catalog import browse_beatport_tracks
    from app.services.recommendation.beatport_genres import resolve_genre_id

    candidates: list[TrackProfile] = []
    total_searched = 0

    # Calculate BPM range from profile
    bpm_min = int(profile.avg_bpm - 15) if profile.avg_bpm else None
    bpm_max = int(profile.avg_bpm + 15) if profile.avg_bpm else None

    # Resolve genre strings to Beatport IDs (deduplicate IDs)
    seen_genre_ids: set[int] = set()
    for genre in profile.dominant_genres[:3]:
        genre_id = resolve_genre_id(genre)
        if genre_id is None or genre_id in seen_genre_ids:
            continue
        seen_genre_ids.add(genre_id)

        results = browse_beatport_tracks(
            db, user, genre_id=genre_id, bpm_min=bpm_min, bpm_max=bpm_max, limit=SEARCH_LIMIT
        )
        for r in results:
            if _filter_beatport_result(r):
                candidates.append(beatport_result_to_profile(r))
        total_searched += len(results)

    return candidates, total_searched


def _search_beatport_text(
    db: Session,
    user: User,
    queries: list[str],
) -> tuple[list[TrackProfile], int]:
    """Search Beatport using text queries (fallback for LLM-generated queries)."""
    from app.services.providers.beatport_catalog import search_beatport_tracks

    candidates: list[TrackProfile] = []
    total_searched = 0
    failures = 0

    for query in queries:
        results = search_beatport_tracks(db, user, query, limit=SEARCH_LIMIT)
        if not results:
            failures += 1
            if failures >= 2:
                logger.warning("Beatport text search failing repeatedly, skipping remaining")
                break
            continue
        for r in results:
            if _filter_beatport_result(r):
                candidates.append(beatport_result_to_profile(r))
        total_searched += len(results)

    return candidates, total_searched


def _build_lb_prompts(
    context: RecommendationContext,
) -> list[str]:
    """Build ListenBrainz Radio prompts from the event profile.

    Returns up to 3 prompts: artist-based (from queue) and tag-based (from genres).
    """
    prompts: list[str] = []

    # Collect unique artists from requests or template tracks.
    artist_counts: dict[str, int] = {}
    if context.requests:
        for req in context.requests:
            artist = getattr(req, "artist", None)
            if artist:
                for individual in split_artists(artist):
                    key = individual.strip()
                    if key.lower() not in ("unknown", "various artists", ""):
                        artist_counts[key] = artist_counts.get(key, 0) + 1
    if context.template_tracks:
        for t in context.template_tracks:
            if t.artist:
                for individual in split_artists(t.artist):
                    key = individual.strip()
                    if key.lower() not in ("unknown", "various artists", ""):
                        artist_counts[key] = artist_counts.get(key, 0) + 1

    top_artists = sorted(artist_counts, key=lambda artist: artist_counts[artist], reverse=True)

    # Prompt 1: top artist from the queue (similar-artist discovery)
    if top_artists:
        prompts.append(f"artist:({top_artists[0]})")

    # Prompt 2-3: genre tags for broader discovery
    for genre in context.event_profile.dominant_genres[:2]:
        if len(prompts) >= 3:
            break
        # Clean genre for LB tag format (lowercase, strip parentheticals)
        tag = genre.split("(")[0].strip().lower()
        if tag:
            prompts.append(f"tag:({tag})")

    # Fallback: more artists if no genres
    if len(prompts) < 2:
        for artist in top_artists[1:]:
            if len(prompts) >= 3:
                break
            prompts.append(f"artist:({artist})")

    return prompts


def _search_tidal_via_lb_radio(
    db: Session,
    user: User,
    context: RecommendationContext,
) -> tuple[list[TrackProfile], int]:
    """Discover tracks via LB Radio, then resolve to playable Tidal tracks.

    Uses ListenBrainz Radio for artist/tag-based discovery, then searches
    Tidal by "artist title" to get playable track IDs.
    Falls back to Soundcharts or text search if LB Radio is unavailable.
    """
    from app.services.providers.listenbrainz import lb_radio_discover
    from app.services.providers.tidal_search import search_tidal_tracks

    profile = context.event_profile
    prompts = _build_lb_prompts(context)
    if not prompts:
        return [], 0

    inferred_genre = profile.dominant_genres[0] if profile.dominant_genres else None
    candidates: list[TrackProfile] = []
    total_searched = 0
    seen_tracks: set[str] = set()  # deduplicate across prompts

    # Cap Tidal lookups per prompt to avoid timeout (each is ~1s)
    max_lookups_per_prompt = 7

    for prompt in prompts:
        lb_tracks = lb_radio_discover(prompt)
        if not lb_tracks:
            continue

        lookups_this_prompt = 0
        for lb_track in lb_tracks:
            # Deduplicate by artist+title
            dedup_key = f"{lb_track.artist.lower()}|{lb_track.title.lower()}"
            if dedup_key in seen_tracks:
                continue
            seen_tracks.add(dedup_key)

            if lookups_this_prompt >= max_lookups_per_prompt:
                break

            # Resolve to Tidal via search
            query = f"{lb_track.artist} {lb_track.title}"
            results = search_tidal_tracks(db, user, query, limit=1)
            total_searched += 1
            lookups_this_prompt += 1

            if not results:
                continue

            r = results[0]
            if is_unwanted_version(r.title):
                continue
            if _is_junk_candidate(r.title, r.artist):
                continue
            if _is_stock_music_artist(r.artist):
                continue

            candidates.append(tidal_result_to_profile(r, inferred_genre=inferred_genre))

    return candidates, total_searched


def _search_tidal_text(
    db: Session,
    user: User,
    queries: list[str],
    profile: EventProfile | None = None,
) -> tuple[list[TrackProfile], int]:
    """Search Tidal using text queries (fallback for LLM or when LB Radio unavailable)."""
    from app.services.providers.tidal_search import search_tidal_tracks

    inferred_genre = profile.dominant_genres[0] if profile and profile.dominant_genres else None
    candidates: list[TrackProfile] = []
    total_searched = 0

    for query in queries:
        results = search_tidal_tracks(db, user, query, limit=SEARCH_LIMIT)
        for r in results:
            if is_unwanted_version(r.title):
                continue
            if _is_junk_candidate(r.title, r.artist):
                continue
            if _is_stock_music_artist(r.artist):
                continue
            candidates.append(tidal_result_to_profile(r, inferred_genre=inferred_genre))
        total_searched += len(results)

    return candidates, total_searched


def _search_candidates(
    db: Session,
    user: User,
    queries: list[str],
    context: RecommendationContext,
    tidal_queries: list[str] | None = None,
) -> tuple[list[TrackProfile], list[str], int]:
    """Search connected services for candidate tracks.

    For Beatport: structured genre/BPM browse when profile is available,
    falls back to text search for LLM-generated queries.
    For Tidal: LB Radio discovery (artist + tag prompts) when configured,
    falls back to Soundcharts or text search.

    Returns (candidates, services_used, total_searched).
    """
    profile = context.event_profile
    candidates: list[TrackProfile] = []
    services_used: set[str] = set()
    total_searched = 0

    # Search Beatport if connected
    if user.beatport_access_token:
        bp_candidates: list[TrackProfile] = []
        bp_searched = 0

        # Prefer structured browse when we have a profile with genres
        if profile and profile.dominant_genres:
            bp_candidates, bp_searched = _search_beatport_structured(db, user, profile)

        # Fall back to text search if structured browse found nothing
        if not bp_candidates:
            bp_candidates, text_searched = _search_beatport_text(db, user, queries)
            bp_searched += text_searched

        candidates.extend(bp_candidates)
        total_searched += bp_searched
        if bp_candidates:
            services_used.add("beatport")

    # Search Tidal if connected
    if user.tidal_access_token:
        tidal_candidates: list[TrackProfile] = []
        tidal_searched = 0

        # Strategy 1: LB Radio discovery (best quality — artist + tag based)
        if profile.dominant_genres or context.requests or context.template_tracks:
            tidal_candidates, lb_searched = _search_tidal_via_lb_radio(db, user, context)
            tidal_searched += lb_searched

        # Strategy 2: Soundcharts discovery (structured genre/BPM/key)
        if not tidal_candidates and profile and profile.dominant_genres:
            from app.core.config import get_settings
            from app.services.recommendation.soundcharts_candidates import (
                search_candidates_via_soundcharts,
            )

            settings = get_settings()
            if settings.soundcharts_app_id and settings.soundcharts_api_key:
                sc_candidates, sc_searched = search_candidates_via_soundcharts(db, user, profile)
                tidal_candidates = _filter_candidates(sc_candidates)
                tidal_searched += sc_searched

        # Strategy 3: Text search fallback (LLM queries or last resort)
        if not tidal_candidates:
            tidal_search_queries = tidal_queries or queries
            tidal_candidates, text_searched = _search_tidal_text(
                db, user, tidal_search_queries, profile
            )
            tidal_searched += text_searched

        candidates.extend(tidal_candidates)
        total_searched += tidal_searched
        if tidal_candidates:
            services_used.add("tidal")

    # Soundcharts related-tracks (#556): provider-agnostic candidate discovery
    # seeded from the event's own tracks (ISRC from the master store). Runs even
    # with NO connected service — that is the whole point of the source. Dark by
    # default: only fires when the paid related endpoint is explicitly enabled
    # AND credentials are configured, so it can never spend by default.
    sc_related_candidates, sc_related_searched = _search_soundcharts_related(db, context.requests)
    if sc_related_candidates:
        candidates.extend(sc_related_candidates)
        total_searched += sc_related_searched
        services_used.add("soundcharts")

    return candidates, sorted(services_used), total_searched


def _filter_candidates(cands: list[TrackProfile]) -> list[TrackProfile]:
    """Drop unwanted/junk/blocked/stock candidates — the shared junk-filter applied
    to every discovery source so the rules live in one place and can't drift."""
    return [
        c
        for c in cands
        if not is_unwanted_version(c.title)
        and not _is_blocked_genre(c.genre)
        and not _is_junk_candidate(c.title, c.artist)
        and not _is_stock_music_artist(c.artist)
    ]


def _search_soundcharts_related(
    db: Session,
    requests: Sequence[Request] | None,
) -> tuple[list[TrackProfile], int]:
    """Discover candidates via the Soundcharts related-tracks source (#556).

    Returns ``([], 0)`` unless the dark-by-default related endpoint is enabled
    and credentials are configured. Seeds from accepted/played requests, then
    junk-filters the results with the same helpers as the other sources.
    """
    if not requests:
        return [], 0

    from app.core.config import get_settings

    settings = get_settings()
    if not settings.soundcharts_related_tracks_enabled:
        return [], 0
    if not settings.soundcharts_app_id or not settings.soundcharts_api_key:
        return [], 0

    from app.services.recommendation.soundcharts_candidates import related_candidates_from_seeds

    related, seeds_used = related_candidates_from_seeds(db, requests)
    return _filter_candidates(related), seeds_used


def soundcharts_related_available() -> bool:
    """True when the dark-by-default Soundcharts related-tracks source can run
    (explicitly enabled AND credentials configured)."""
    from app.core.config import get_settings

    settings = get_settings()
    return bool(
        settings.soundcharts_related_tracks_enabled
        and settings.soundcharts_app_id
        and settings.soundcharts_api_key
    )
