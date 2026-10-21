"""Unified search pipeline: convert, filter, deduplicate, and rank results.

Pluggable architecture:
    Each music service provides a converter function (e.g., tidal_to_search_result)
    that maps service-specific results to the unified SearchResult schema.
    All converters feed into build_search_results(), which applies:
        1. Junk filtering (unwanted versions + compilation detection)
        2. ISRC-based deduplication (exact match across services)
        3. Popularity ranking
        4. Fuzzy deduplication (fallback for tracks without ISRC)

    To add a new service:
        1. Create a converter: ``def new_service_to_search_result(r) -> SearchResult``
        2. Pass converted results via a new kwarg to build_search_results()
        3. Junk filtering is applied to non-curated sources by default
"""

from __future__ import annotations

import re

from app.schemas.beatport import BeatportSearchResult
from app.schemas.search import SearchResult
from app.schemas.tidal import TidalSearchResult
from app.services.track_normalizer import (
    artist_match_score,
    fuzzy_match_score,
    score_track_match,
)
from app.services.version_filter import is_unwanted_version

# --- Compilation / junk detection for main titles ---
# Matches workout compilations, cardio playlists, tribute albums, DJ mix compilations.
_COMPILATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(?:workout|cardio|fitness|exercise|gym|running|spinning|training)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\btribute\s+(?:to|album)\b", re.IGNORECASE),
    re.compile(r"\bPt\.\s*\d+", re.IGNORECASE),  # "Pt. 30", "Pt. 1"
    re.compile(r"\bDJ\s+Mix\b", re.IGNORECASE),
    re.compile(r"\b(?:non[\s-]?stop|megamix|minimix|continuous)\s+mix\b", re.IGNORECASE),
    re.compile(r"\bmade\s+famous\s+by\b", re.IGNORECASE),
    re.compile(r"\boriginally\s+performed\s+by\b", re.IGNORECASE),
]


def _is_compilation(title: str) -> bool:
    """Detect compilation/junk titles that shouldn't appear in search results.

    Catches workout mixes, cardio playlists, "Pt. N" series, tribute albums,
    and DJ mix compilations. Unlike version_filter which checks parenthetical
    tags, this checks the main title text.
    """
    for pattern in _COMPILATION_PATTERNS:
        if pattern.search(title):
            return True
    return False


def _is_duplicate(
    candidate: SearchResult,
    existing: list[SearchResult],
    threshold: float,
) -> bool:
    """Check if a candidate result is a fuzzy duplicate of any existing result."""
    for result in existing:
        title_score = fuzzy_match_score(candidate.title, result.title)
        artist_score = artist_match_score(candidate.artist, result.artist)
        combined = score_track_match(title_score, artist_score)
        if combined >= threshold:
            return True
    return False


def tidal_to_search_result(t: TidalSearchResult) -> SearchResult:
    """Convert a TidalSearchResult to the unified SearchResult format."""
    return SearchResult(
        artist=t.artist,
        title=t.title,
        album=t.album,
        popularity=t.popularity,
        spotify_id=None,
        album_art=t.cover_url,
        preview_url=None,
        url=t.tidal_url,
        source="tidal",
        genre=None,
        bpm=int(t.bpm) if t.bpm else None,
        key=t.key,
        isrc=t.isrc,
    )


def _beatport_to_search_result(bp: BeatportSearchResult) -> SearchResult:
    """Convert a BeatportSearchResult to the unified SearchResult format."""
    return SearchResult(
        artist=bp.artist,
        title=bp.title,
        album=None,
        popularity=0,
        spotify_id=None,
        album_art=bp.cover_url,
        preview_url=None,
        url=bp.beatport_url,
        source="beatport",
        genre=bp.genre,
        bpm=bp.bpm,
        key=bp.key,
    )


def _isrc_dedup_merge(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate results sharing the same ISRC, keeping best metadata.

    When the same recording appears on multiple services (same ISRC), we keep
    the version with the highest popularity and merge in any missing metadata
    (BPM, key, genre) from the other copies.
    """
    isrc_groups: dict[str, list[SearchResult]] = {}
    no_isrc: list[SearchResult] = []

    for r in results:
        if r.isrc:
            isrc_groups.setdefault(r.isrc, []).append(r)
        else:
            no_isrc.append(r)

    merged: list[SearchResult] = []
    for group in isrc_groups.values():
        # Pick the result with highest popularity as the base
        best = max(group, key=lambda r: r.popularity)

        # Merge missing metadata from other copies
        for other in group:
            if other is best:
                continue
            updates: dict = {}
            if not best.bpm and other.bpm:
                updates["bpm"] = other.bpm
            if not best.key and other.key:
                updates["key"] = other.key
            if not best.genre and other.genre:
                updates["genre"] = other.genre
            if not best.album_art and other.album_art:
                updates["album_art"] = other.album_art
            if updates:
                best = best.model_copy(update=updates)

        merged.append(best)

    return merged + no_isrc


def build_search_results(
    tidal_results: list[TidalSearchResult] | None = None,
    spotify_results: list[SearchResult] | None = None,
    beatport_results: list[BeatportSearchResult] | None = None,
    intent: object | None = None,
    dedup_threshold: float = 0.8,
    max_beatport_extras: int = 5,
) -> list[SearchResult]:
    """Unified search pipeline: convert, filter, deduplicate, and rank.

    Pipeline steps:
        1. Convert all source results to SearchResult
        2. Junk filter on Tidal/Spotify (not Beatport — DJ-curated catalog)
        3. ISRC dedup+merge (same recording across services → single result)
        4. Rank candidates by popularity, then fuzzy dedup (keep the top candidate)
        5. Append Beatport extras after the ranked main results

    Args:
        tidal_results: Results from Tidal search (primary source).
        spotify_results: Results from Spotify search (fallback source).
        beatport_results: Results from Beatport search (event-level toggle).
        intent: Parsed IntentContext from parse_intent() — controls version filtering.
        dedup_threshold: Fuzzy match threshold for deduplication.
        max_beatport_extras: Maximum Beatport-only results to append.

    Returns:
        Unified, filtered, deduplicated, and ranked list of SearchResult.
    """
    # Step 1: Convert all sources to SearchResult
    converted_main: list[SearchResult] = []

    if tidal_results:
        for t in tidal_results:
            converted_main.append(tidal_to_search_result(t))

    if spotify_results:
        converted_main.extend(spotify_results)

    converted_beatport: list[SearchResult] = []
    if beatport_results:
        for bp in beatport_results:
            converted_beatport.append(_beatport_to_search_result(bp))

    # Step 2: Junk filter on main results (not Beatport — DJ-curated)
    filtered_main: list[SearchResult] = []
    for r in converted_main:
        if is_unwanted_version(r.title, intent):
            continue
        if _is_compilation(r.title):
            continue
        filtered_main.append(r)

    # Step 3: ISRC dedup+merge
    deduped = _isrc_dedup_merge(filtered_main)

    # Step 4: Rank first so fuzzy duplicates keep the most popular representative.
    # Sorting is stable, so equal-ranked results retain Tidal's primary-source order.
    deduped.sort(key=lambda result: result.popularity, reverse=True)

    # Step 5: Fuzzy dedup within main results
    unique_main: list[SearchResult] = []
    for r in deduped:
        if not _is_duplicate(r, unique_main, dedup_threshold):
            unique_main.append(r)

    # Step 6: Append unique Beatport extras (dedup against main results)
    added_bp = 0
    for bp in converted_beatport:
        if added_bp >= max_beatport_extras:
            break
        if not _is_duplicate(bp, unique_main, dedup_threshold):
            unique_main.append(bp)
            added_bp += 1

    return unique_main
