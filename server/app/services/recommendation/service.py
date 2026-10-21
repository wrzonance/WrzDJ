"""Recommendation engine orchestrator.

Coordinates enrichment, profiling, candidate search, scoring,
and deduplication to generate track suggestions for an event.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.services.recommendation.candidate_search import (
    _is_blocked_genre as _is_blocked_genre,
)
from app.services.recommendation.candidate_search import (
    _is_junk_candidate as _is_junk_candidate,
)
from app.services.recommendation.candidate_search import (
    _is_stock_music_artist as _is_stock_music_artist,
)
from app.services.recommendation.candidate_search import (
    _search_candidates,
    soundcharts_related_available,
)
from app.services.recommendation.context import RecommendationContext
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
    build_event_profile,
    rank_candidates,
)
from app.services.track_normalizer import artist_match_score

logger = logging.getLogger(__name__)

# Maximum results per search query
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
    mb_verified: dict[str, bool] = field(default_factory=dict)


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
    mb_verified: dict[str, bool] = field(default_factory=dict)


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
    context = RecommendationContext(
        event_profile=profile,
        accepted_tracks=enriched,
        rejected_tracks=rejected_names,
        currently_playing=currently_playing,
        requests=requests,
    )

    # Step 2: Call LLM (pass enriched tracks + rejected + currently playing).
    # Route via the gateway by supplying db + actor (the event owner).
    llm_result = await generate_llm_suggestions(
        context,
        prompt,
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
        context,
        tidal_queries=llm_query_strings,
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
        RecommendationContext(event_profile=profile, template_tracks=template_tracks),
        tidal_queries=tidal_queries or None,
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

    # Check if any candidate source is available. Tidal/Beatport need a connected
    # account; the Soundcharts related-tracks source (#556) is provider-agnostic
    # and works with no connected service, so it keeps recommendations alive for a
    # DJ who hasn't linked anything — when explicitly enabled (dark by default).
    has_tidal = bool(user.tidal_access_token)
    has_beatport = bool(user.beatport_access_token)
    has_soundcharts_related = soundcharts_related_available()

    if not has_tidal and not has_beatport and not has_soundcharts_related:
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
        RecommendationContext(event_profile=profile, requests=requests),
        tidal_queries=tidal_queries or None,
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
