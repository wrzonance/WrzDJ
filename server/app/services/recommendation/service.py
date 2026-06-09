"""Recommendation engine orchestrator.

Coordinates enrichment, profiling, candidate search, scoring,
and deduplication to generate track suggestions for an event.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.recommendation.deduplication import (
    deduplicate_against_requests,
    deduplicate_against_template,
    deduplicate_candidates,
)
from app.services.recommendation.enrichment import enrich_event_tracks
from app.services.recommendation.llm_hooks import LLMSuggestionQuery
from app.services.recommendation.query_builder import (
    build_beatport_queries,
    build_tidal_queries,
)
from app.services.recommendation.scorer import (
    EventProfile,
    ScoredTrack,
    TrackProfile,
    build_event_profile,
    rank_candidates,
)
from app.services.track_normalizer import artist_match_score, split_artists
from app.services.version_filter import is_unwanted_version

logger = logging.getLogger(__name__)

# Maximum results per search query
SEARCH_LIMIT = 10

# Penalty multiplier for candidates matching a source artist (already in queue)
SOURCE_ARTIST_PENALTY = 0.50
# Base penalty for repeated artists among candidates (compounds per occurrence)
REPEAT_ARTIST_BASE_PENALTY = 0.75
# Fuzzy match threshold for artist matching
ARTIST_MATCH_THRESHOLD = 0.85
# Hard cap on tracks per artist in final output
MAX_PER_ARTIST = 2
# Over-fetch multiplier: score more candidates before applying diversity + cap
OVERFETCH_MULTIPLIER = 3

# Genres that indicate non-music or DJ utility tracks
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


# BPM delta threshold for detecting a vibe shift
VIBE_SHIFT_BPM_DELTA = 15


def _build_llm_scoring_profile(
    queries: list[LLMSuggestionQuery],
    original_profile: EventProfile,
) -> EventProfile:
    """Build a synthetic scoring profile from LLM query targets when a vibe shift is detected.

    If the majority of queries (>=50%) have targets that differ significantly from
    the original event profile (BPM delta >15 or non-overlapping genres), returns a
    synthetic EventProfile built from the LLM targets. Otherwise returns the original
    profile unchanged.
    """
    if not queries:
        return original_profile

    # Collect non-None targets
    target_bpms = [q.target_bpm for q in queries if q.target_bpm is not None]
    target_genres = [q.target_genre for q in queries if q.target_genre is not None]
    target_keys = [q.target_key for q in queries if q.target_key is not None]

    # Count how many queries have any target metadata
    queries_with_targets = sum(
        1
        for q in queries
        if q.target_bpm is not None or q.target_genre is not None or q.target_key is not None
    )

    # Need majority of queries to have targets
    if queries_with_targets < len(queries) / 2:
        return original_profile

    # Detect vibe shift: significant BPM difference or non-overlapping genres
    is_shift = False

    if target_bpms and original_profile.avg_bpm is not None:
        avg_target_bpm = sum(target_bpms) / len(target_bpms)
        if abs(avg_target_bpm - original_profile.avg_bpm) > VIBE_SHIFT_BPM_DELTA:
            is_shift = True

    if target_genres and original_profile.dominant_genres:
        original_genres_lower = {g.lower() for g in original_profile.dominant_genres}
        target_genres_lower = {g.lower() for g in target_genres}
        if not original_genres_lower & target_genres_lower:
            is_shift = True

    # Also shift if original profile is empty (no data to compare against)
    if original_profile.track_count == 0 and (target_bpms or target_genres):
        is_shift = True

    if not is_shift:
        return original_profile

    # Build synthetic profile from LLM targets
    avg_bpm = sum(target_bpms) / len(target_bpms) if target_bpms else original_profile.avg_bpm
    bpm_range = (min(target_bpms), max(target_bpms)) if len(target_bpms) >= 2 else None

    # Deduplicate genres/keys preserving order
    seen_genres: list[str] = []
    for g in target_genres:
        if g not in seen_genres:
            seen_genres.append(g)
    seen_keys: list[str] = []
    for k in target_keys:
        if k not in seen_keys:
            seen_keys.append(k)

    return EventProfile(
        avg_bpm=avg_bpm,
        bpm_range=bpm_range,
        dominant_keys=seen_keys or list(original_profile.dominant_keys),
        dominant_genres=seen_genres or list(original_profile.dominant_genres),
        track_count=original_profile.track_count,
    )


def _apply_artist_diversity(
    scored: list[ScoredTrack],
    source_artists: set[str],
) -> list[ScoredTrack]:
    """Apply artist diversity penalties and re-rank.

    Two-layer penalty keeps the scorer module pure (musical compatibility only)
    while the orchestrator promotes variety across artists.

    Layer 1 — Source artist penalty: if a candidate's artist matches an artist
    already in the source material (accepted requests or template playlist),
    apply SOURCE_ARTIST_PENALTY to its score.

    Layer 2 — Repetition penalty: among candidates sharing an artist, the 2nd
    occurrence gets REPEAT_ARTIST_BASE_PENALTY, 3rd gets 0.80, etc.
    """
    artist_seen_count: dict[str, int] = {}
    adjusted: list[ScoredTrack] = []

    for st in scored:
        multiplier = 1.0
        candidate_artist = st.profile.artist.lower() if st.profile.artist else ""

        # Layer 1: penalize if artist is already in the source material
        if candidate_artist:
            for src in source_artists:
                if artist_match_score(candidate_artist, src) >= ARTIST_MATCH_THRESHOLD:
                    multiplier *= SOURCE_ARTIST_PENALTY
                    break

        # Layer 2: penalize repeated artists among candidates
        if candidate_artist:
            count = artist_seen_count.get(candidate_artist, 0)
            # Find the canonical key (handles slight case variations already
            # normalised by .lower(), but also check fuzzy against seen keys)
            matched_key = candidate_artist
            for seen_key in artist_seen_count:
                if artist_match_score(candidate_artist, seen_key) >= ARTIST_MATCH_THRESHOLD:
                    matched_key = seen_key
                    count = artist_seen_count[seen_key]
                    break

            if count > 0:
                # 1st dup -> 0.75, 2nd dup -> 0.65, 3rd -> 0.55, 4th -> 0.45, floor at 0.30
                penalty = max(REPEAT_ARTIST_BASE_PENALTY - 0.10 * (count - 1), 0.30)
                multiplier *= penalty

            artist_seen_count[matched_key] = count + 1

        new_score = st.score * multiplier
        adjusted.append(
            ScoredTrack(
                profile=st.profile,
                score=new_score,
                bpm_score=st.bpm_score,
                key_score=st.key_score,
                genre_score=st.genre_score,
            )
        )

    adjusted.sort(key=lambda s: s.score, reverse=True)
    return adjusted


def _enforce_artist_cap(
    scored: list[ScoredTrack],
    max_per_artist: int,
) -> list[ScoredTrack]:
    """Enforce a hard cap on tracks per artist in the final output.

    Iterates through scored tracks (already sorted by score descending)
    and skips any track whose artist has already appeared max_per_artist
    times. Uses fuzzy matching to consolidate name variations.
    """
    artist_counts: dict[str, int] = {}
    capped: list[ScoredTrack] = []

    for st in scored:
        artist_key = st.profile.artist.lower() if st.profile.artist else ""

        # Empty-artist tracks are always allowed through (no meaningful cap)
        if not artist_key:
            capped.append(st)
            continue

        # Find canonical key via fuzzy matching against already-seen artists
        matched_key = artist_key
        for seen_key in artist_counts:
            if artist_match_score(artist_key, seen_key) >= ARTIST_MATCH_THRESHOLD:
                matched_key = seen_key
                break

        count = artist_counts.get(matched_key, 0)
        if count >= max_per_artist:
            continue

        artist_counts[matched_key] = count + 1
        capped.append(st)

    return capped


@dataclass
class RecommendationResult:
    """Result of generating recommendations for an event."""

    suggestions: list[ScoredTrack]
    event_profile: EventProfile
    enriched_count: int
    total_candidates_searched: int
    services_used: list[str]
    mb_verified: dict[str, bool] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.mb_verified is None:
            self.mb_verified = {}


def _get_accepted_played_requests(db: Session, event: Event) -> list[Request]:
    """Fetch accepted and played requests for the event, most recent first."""
    return (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.status.in_([RequestStatus.ACCEPTED.value, RequestStatus.PLAYED.value]),
        )
        .order_by(Request.created_at.desc())
        .all()
    )


def _get_rejected_requests(db: Session, event: Event) -> list[Request]:
    """Fetch rejected requests for the event (most recent first, capped at 20)."""
    return (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.status == RequestStatus.REJECTED.value,
        )
        .order_by(Request.created_at.desc())
        .limit(20)
        .all()
    )


def _get_currently_playing(db: Session, event: Event) -> Request | None:
    """Fetch the currently playing request for the event, if any."""
    return (
        db.query(Request)
        .filter(
            Request.event_id == event.id,
            Request.status == RequestStatus.PLAYING.value,
        )
        .first()
    )


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


def _beatport_result_to_profile(r) -> TrackProfile:
    """Convert a BeatportSearchResult to a TrackProfile."""
    return TrackProfile(
        title=r.title,
        artist=r.artist,
        bpm=float(r.bpm) if r.bpm else None,
        key=r.key,
        genre=r.genre,
        source="beatport",
        track_id=r.track_id,
        url=r.beatport_url,
        cover_url=r.cover_url,
        duration_seconds=r.duration_seconds,
    )


def _search_beatport_structured(
    db: Session,
    user: User,
    profile: EventProfile,
) -> tuple[list[TrackProfile], int]:
    """Search Beatport using structured genre/BPM/key browse.

    Falls back to text search if no genre IDs can be resolved.
    Returns (candidates, total_searched).
    """
    from app.services.beatport import browse_beatport_tracks
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
                candidates.append(_beatport_result_to_profile(r))
        total_searched += len(results)

    return candidates, total_searched


def _search_beatport_text(
    db: Session,
    user: User,
    queries: list[str],
) -> tuple[list[TrackProfile], int]:
    """Search Beatport using text queries (fallback for LLM-generated queries)."""
    from app.services.beatport import search_beatport_tracks

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
                candidates.append(_beatport_result_to_profile(r))
        total_searched += len(results)

    return candidates, total_searched


def _build_lb_prompts(
    profile: EventProfile,
    requests: list | None = None,
    template_tracks: list[TrackProfile] | None = None,
) -> list[str]:
    """Build ListenBrainz Radio prompts from the event profile.

    Returns up to 3 prompts: artist-based (from queue) and tag-based (from genres).
    """
    prompts: list[str] = []

    # Collect unique artists from requests or template tracks
    artist_counts: dict[str, int] = {}
    if requests:
        for req in requests:
            artist = getattr(req, "artist", None)
            if artist:
                for individual in split_artists(artist):
                    key = individual.strip()
                    if key.lower() not in ("unknown", "various artists", ""):
                        artist_counts[key] = artist_counts.get(key, 0) + 1
    if template_tracks:
        for t in template_tracks:
            if t.artist:
                for individual in split_artists(t.artist):
                    key = individual.strip()
                    if key.lower() not in ("unknown", "various artists", ""):
                        artist_counts[key] = artist_counts.get(key, 0) + 1

    top_artists = sorted(artist_counts, key=artist_counts.get, reverse=True)  # type: ignore[arg-type]

    # Prompt 1: top artist from the queue (similar-artist discovery)
    if top_artists:
        prompts.append(f"artist:({top_artists[0]})")

    # Prompt 2-3: genre tags for broader discovery
    for genre in profile.dominant_genres[:2]:
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
    profile: EventProfile,
    requests: list | None = None,
    template_tracks: list[TrackProfile] | None = None,
) -> tuple[list[TrackProfile], int]:
    """Discover tracks via LB Radio, then resolve to playable Tidal tracks.

    Uses ListenBrainz Radio for artist/tag-based discovery, then searches
    Tidal by "artist title" to get playable track IDs.
    Falls back to Soundcharts or text search if LB Radio is unavailable.
    """
    from app.services.listenbrainz import lb_radio_discover
    from app.services.tidal import search_tidal_tracks

    prompts = _build_lb_prompts(profile, requests, template_tracks)
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

            candidates.append(
                TrackProfile(
                    title=r.title,
                    artist=r.artist,
                    bpm=r.bpm,
                    key=r.key,
                    genre=inferred_genre,
                    source="tidal",
                    track_id=r.track_id,
                    url=r.tidal_url,
                    cover_url=r.cover_url,
                    duration_seconds=r.duration_seconds,
                )
            )

    return candidates, total_searched


def _search_tidal_text(
    db: Session,
    user: User,
    queries: list[str],
    profile: EventProfile | None = None,
) -> tuple[list[TrackProfile], int]:
    """Search Tidal using text queries (fallback for LLM or when LB Radio unavailable)."""
    from app.services.tidal import search_tidal_tracks

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
            candidates.append(
                TrackProfile(
                    title=r.title,
                    artist=r.artist,
                    bpm=r.bpm,
                    key=r.key,
                    genre=inferred_genre,
                    source="tidal",
                    track_id=r.track_id,
                    url=r.tidal_url,
                    cover_url=r.cover_url,
                    duration_seconds=r.duration_seconds,
                )
            )
        total_searched += len(results)

    return candidates, total_searched


def _search_candidates(
    db: Session,
    user: User,
    queries: list[str],
    profile: EventProfile | None = None,
    tidal_queries: list[str] | None = None,
    requests: list | None = None,
    template_tracks: list[TrackProfile] | None = None,
) -> tuple[list[TrackProfile], list[str], int]:
    """Search connected services for candidate tracks.

    For Beatport: structured genre/BPM browse when profile is available,
    falls back to text search for LLM-generated queries.
    For Tidal: LB Radio discovery (artist + tag prompts) when configured,
    falls back to Soundcharts or text search.

    Returns (candidates, services_used, total_searched).
    """
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
            bp_candidates, bp_searched = _search_beatport_text(db, user, queries)

        candidates.extend(bp_candidates)
        total_searched += bp_searched
        if bp_candidates:
            services_used.add("beatport")

    # Search Tidal if connected
    if user.tidal_access_token:
        tidal_candidates: list[TrackProfile] = []
        tidal_searched = 0

        # Strategy 1: LB Radio discovery (best quality — artist + tag based)
        if profile and (profile.dominant_genres or requests or template_tracks):
            tidal_candidates, tidal_searched = _search_tidal_via_lb_radio(
                db, user, profile, requests=requests, template_tracks=template_tracks
            )

        # Strategy 2: Soundcharts discovery (structured genre/BPM/key)
        if not tidal_candidates and profile and profile.dominant_genres:
            from app.core.config import get_settings
            from app.services.recommendation.soundcharts_candidates import (
                search_candidates_via_soundcharts,
            )

            settings = get_settings()
            if settings.soundcharts_app_id and settings.soundcharts_api_key:
                sc_candidates, sc_searched = search_candidates_via_soundcharts(db, user, profile)
                tidal_candidates = [
                    c
                    for c in sc_candidates
                    if not is_unwanted_version(c.title)
                    and not _is_blocked_genre(c.genre)
                    and not _is_junk_candidate(c.title, c.artist)
                    and not _is_stock_music_artist(c.artist)
                ]
                tidal_searched = sc_searched

        # Strategy 3: Text search fallback (LLM queries or last resort)
        if not tidal_candidates:
            tidal_search_queries = tidal_queries or queries
            tidal_candidates, tidal_searched = _search_tidal_text(
                db, user, tidal_search_queries, profile
            )

        candidates.extend(tidal_candidates)
        total_searched += tidal_searched
        if tidal_candidates:
            services_used.add("tidal")

    return candidates, sorted(services_used), total_searched


def _filter_unverified_artists(
    db: Session,
    scored: list[ScoredTrack],
) -> tuple[list[ScoredTrack], dict[str, bool]]:
    """Remove tracks by artists not found in MusicBrainz.

    Returns the filtered list and the verification dict for the frontend badge.
    """
    from app.services.recommendation.mb_verify import verify_artists_batch

    artist_names = [s.profile.artist for s in scored if s.profile.artist]
    if not artist_names:
        return scored, {}

    mb_verified = verify_artists_batch(db, artist_names)

    filtered = [
        s for s in scored if not s.profile.artist or mb_verified.get(s.profile.artist, False)
    ]
    return filtered, mb_verified


@dataclass
class LLMRecommendationResult:
    """Result of LLM-powered recommendations."""

    suggestions: list[ScoredTrack]
    event_profile: EventProfile
    enriched_count: int
    total_candidates_searched: int
    services_used: list[str]
    llm_queries: list  # list of LLMSuggestionQuery
    llm_model: str | None = None  # Provider model that produced the queries
    mb_verified: dict[str, bool] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.mb_verified is None:
            self.mb_verified = {}


async def generate_recommendations_from_llm(
    db: Session,
    user: User,
    event: Event,
    prompt: str,
    max_results: int = 20,
) -> LLMRecommendationResult:
    """Generate recommendations using LLM-generated search queries.

    Pipeline:
    1. Build EventProfile from accepted/played requests
    2. Call LLM with profile + DJ prompt -> structured search queries
    3. Search Tidal/Beatport with LLM query strings
    4. Deduplicate, score, rank, apply artist diversity
    """
    from app.services.recommendation.llm_hooks import generate_llm_suggestions

    # Step 1: Build event profile (same as algorithmic path)
    requests = _get_accepted_played_requests(db, event)
    enriched = enrich_event_tracks(db, user, requests) if requests else []
    profile = build_event_profile(enriched)

    # Gather extra context for the LLM
    rejected = _get_rejected_requests(db, event)
    rejected_names = [(r.artist, r.song_title) for r in rejected] if rejected else []
    playing = _get_currently_playing(db, event)
    currently_playing = (
        (playing.artist, playing.song_title, getattr(playing, "bpm", None)) if playing else None
    )

    # Step 2: Call LLM (pass enriched tracks + rejected + currently playing).
    # Route via the gateway by supplying db + actor (the event owner).
    llm_result = await generate_llm_suggestions(
        profile,
        prompt,
        tracks=enriched or None,
        rejected_tracks=rejected_names or None,
        currently_playing=currently_playing,
        db=db,
        actor=user,
    )

    if not llm_result.queries:
        return LLMRecommendationResult(
            suggestions=[],
            event_profile=profile,
            enriched_count=len(enriched),
            total_candidates_searched=0,
            services_used=[],
            llm_queries=[],
            llm_model=llm_result.model,
        )

    # Step 3: Use LLM query strings as search queries
    llm_query_strings = [q.search_query for q in llm_result.queries]

    candidates, services_used, total_searched = _search_candidates(
        db,
        user,
        llm_query_strings,
        profile=profile,
        tidal_queries=llm_query_strings,
        requests=requests,
    )

    # Step 4: Deduplicate
    candidates = deduplicate_candidates(candidates)
    all_requests = db.query(Request).filter(Request.event_id == event.id).all()
    candidates = deduplicate_against_requests(candidates, all_requests)
    # Also deduplicate against enriched tracks (catches songs referenced in
    # the prompt that are already in the set, even if stored slightly differently)
    if enriched:
        candidates = deduplicate_against_template(candidates, enriched)

    # Step 5: Score and rank (over-fetch; use LLM targets if vibe shift detected)
    scoring_profile = _build_llm_scoring_profile(llm_result.queries, profile)
    ranked = rank_candidates(candidates, scoring_profile, max_results * OVERFETCH_MULTIPLIER)

    # Step 6: Artist diversity, enforce hard cap, then truncate
    source_artists = {req.artist.lower() for req in requests if req.artist}
    ranked = _apply_artist_diversity(ranked, source_artists)
    ranked = _enforce_artist_cap(ranked, MAX_PER_ARTIST)
    ranked, mb_verified = _filter_unverified_artists(db, ranked)
    ranked = ranked[:max_results]

    logger.info(
        "Generated %d LLM recommendations for event %s (prompt=%s, queries=%d, candidates=%d)",
        len(ranked),
        event.code,
        prompt[:50],
        len(llm_result.queries),
        len(candidates),
    )

    return LLMRecommendationResult(
        suggestions=ranked,
        event_profile=profile,
        enriched_count=len(enriched),
        total_candidates_searched=total_searched,
        services_used=services_used,
        llm_queries=llm_result.queries,
        llm_model=llm_result.model,
        mb_verified=mb_verified,
    )


def generate_recommendations_from_template(
    db: Session,
    user: User,
    event: Event,
    template_source: str,
    template_id: str,
    max_results: int = 20,
) -> RecommendationResult:
    """Generate recommendations using a template playlist as the profile source.

    The template playlist's tracks build the EventProfile instead of the
    event's accepted requests. The rest of the pipeline is reused.
    """
    from app.services.recommendation.template import (
        tracks_from_beatport_playlist,
        tracks_from_tidal_playlist,
    )

    if template_source == "tidal":
        template_tracks = tracks_from_tidal_playlist(db, user, template_id)
    elif template_source == "beatport":
        template_tracks = tracks_from_beatport_playlist(db, user, template_id)
    else:
        raise ValueError(f"Invalid template source: {template_source}")

    if not template_tracks:
        return RecommendationResult(
            suggestions=[],
            event_profile=EventProfile(track_count=0),
            enriched_count=0,
            total_candidates_searched=0,
            services_used=[],
        )

    # Build profile from template tracks (no enrichment needed — data is direct)
    profile = build_event_profile(template_tracks)

    # Generate search queries from profile (pass template tracks for artist fallback)
    search_queries = build_beatport_queries(profile, template_tracks=template_tracks)
    if not search_queries:
        search_queries = ["top tracks", "popular tracks"]

    # Build artist-based queries for Tidal text search (genre strings don't work)
    tidal_queries = build_tidal_queries(profile, template_tracks=template_tracks)

    # Search for candidates
    candidates, services_used, total_searched = _search_candidates(
        db,
        user,
        search_queries,
        profile=profile,
        tidal_queries=tidal_queries or None,
        template_tracks=template_tracks,
    )

    # Deduplicate candidates among themselves
    candidates = deduplicate_candidates(candidates)

    # Deduplicate against event's existing requests (not the template)
    all_requests = db.query(Request).filter(Request.event_id == event.id).all()
    candidates = deduplicate_against_requests(candidates, all_requests)

    # Also deduplicate against the template tracks themselves
    candidates = deduplicate_against_template(candidates, template_tracks)

    # Score and rank (over-fetch to give diversity room to work)
    ranked = rank_candidates(candidates, profile, max_results * OVERFETCH_MULTIPLIER)

    # Apply artist diversity penalties, enforce hard cap, then truncate
    source_artists = {t.artist.lower() for t in template_tracks if t.artist}
    ranked = _apply_artist_diversity(ranked, source_artists)
    ranked = _enforce_artist_cap(ranked, MAX_PER_ARTIST)
    ranked, mb_verified = _filter_unverified_artists(db, ranked)
    ranked = ranked[:max_results]

    logger.info(
        "Generated %d template recommendations for event %s "
        "(template=%s:%s, queries=%s, candidates=%d, searched=%d)",
        len(ranked),
        event.code,
        template_source,
        template_id,
        search_queries,
        len(candidates),
        total_searched,
    )

    return RecommendationResult(
        suggestions=ranked,
        event_profile=profile,
        enriched_count=len(template_tracks),
        total_candidates_searched=total_searched,
        services_used=services_used,
        mb_verified=mb_verified,
    )


def generate_recommendations(
    db: Session,
    user: User,
    event: Event,
    max_results: int = 20,
) -> RecommendationResult:
    """Generate track recommendations for an event.

    Pipeline:
    1. Fetch accepted/played requests
    2. Enrich with BPM/key/genre from Tidal/Beatport
    3. Build EventProfile
    4. Generate search queries from profile
    5. Search connected services for candidates
    6. Deduplicate against existing requests
    7. Score and rank candidates
    8. Return top N
    """
    # Step 1: Fetch existing requests
    requests = _get_accepted_played_requests(db, event)

    # Check if any services are connected
    has_tidal = bool(user.tidal_access_token)
    has_beatport = bool(user.beatport_access_token)

    if not has_tidal and not has_beatport:
        return RecommendationResult(
            suggestions=[],
            event_profile=EventProfile(track_count=0),
            enriched_count=0,
            total_candidates_searched=0,
            services_used=[],
        )

    # Step 2: Enrich tracks
    enriched = enrich_event_tracks(db, user, requests) if requests else []

    # Step 3: Build profile
    profile = build_event_profile(enriched)

    # Step 4: Generate search queries (for Beatport)
    search_queries = build_beatport_queries(profile)

    # If no queries can be generated (no genre, no BPM), use generic queries
    if not search_queries:
        search_queries = ["top tracks", "popular tracks"]

    # Build artist-based queries for Tidal text search (genre strings don't work)
    tidal_queries = build_tidal_queries(profile, requests=requests)

    # Step 5: Search for candidates
    candidates, services_used, total_searched = _search_candidates(
        db,
        user,
        search_queries,
        profile=profile,
        tidal_queries=tidal_queries or None,
        requests=requests,
    )

    # Step 6a: Deduplicate candidates among themselves
    candidates = deduplicate_candidates(candidates)

    # Step 6b: Deduplicate against existing requests
    all_requests = db.query(Request).filter(Request.event_id == event.id).all()
    candidates = deduplicate_against_requests(candidates, all_requests)

    # Step 7: Score and rank (over-fetch to give diversity room to work)
    ranked = rank_candidates(candidates, profile, max_results * OVERFETCH_MULTIPLIER)

    # Step 8: Apply artist diversity penalties, enforce hard cap, then truncate
    source_artists = {req.artist.lower() for req in requests if req.artist}
    ranked = _apply_artist_diversity(ranked, source_artists)
    ranked = _enforce_artist_cap(ranked, MAX_PER_ARTIST)
    ranked, mb_verified = _filter_unverified_artists(db, ranked)
    ranked = ranked[:max_results]

    logger.info(
        "Generated %d recommendations for event %s (enriched=%d, candidates=%d, searched=%d)",
        len(ranked),
        event.code,
        len(enriched),
        len(candidates),
        total_searched,
    )

    return RecommendationResult(
        suggestions=ranked,
        event_profile=profile,
        enriched_count=len(enriched),
        total_candidates_searched=total_searched,
        services_used=services_used,
        mb_verified=mb_verified,
    )
