"""Unified best-match selector for fuzzy search results (#551).

`find_best_match` is the SINGLE place that picks the best-scoring search result
for a (title, artist) query. It is shared by the request enrichment pipeline,
the collect search-time preview, and the recommendation Tidal/Beatport
enrichers, which previously carried three slightly-different copies of this
logic — two of them missing the artist-score floor and the BPM-consensus
tiebreaker, which let a perfect-title/wrong-artist result win.

Field access goes through small accessor callables so the one implementation
works across result shapes: Beatport/search results expose ``.title``/``.artist``/
``.mix_name``/``.bpm`` (the defaults), while a tidalapi ``Track`` exposes
``.name`` and needs a custom artist accessor — the caller passes ``get_title`` /
``get_artist`` for those.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.services.track_normalizer import (
    artist_match_score,
    fuzzy_match_score,
    is_original_mix_name,
    is_remix_title,
    score_track_match,
)

logger = logging.getLogger(__name__)


def _default_bpm(result: Any) -> float | None:
    return getattr(result, "bpm", None)


def _default_mix_name(result: Any) -> str | None:
    return getattr(result, "mix_name", None)


def find_best_match(
    results,
    title: str,
    artist: str,
    *,
    min_score: float = 0.4,
    min_artist_score: float = 0.35,
    prefer_original: bool = True,
    get_title: Callable[[Any], str] = lambda r: r.title,
    get_artist: Callable[[Any], str] = lambda r: r.artist,
    get_bpm: Callable[[Any], float | None] = _default_bpm,
    get_mix_name: Callable[[Any], str | None] = _default_mix_name,
):
    """Return the best fuzzy match from ``results`` for the (title, artist) query.

    Scores each result by title (60%) + artist (40%) similarity and returns the
    best result whose combined score is >= ``min_score``, else ``None``.

    A separate ``min_artist_score`` floor discards results whose artist is
    nowhere near the query, so a perfect title can't carry a completely wrong
    artist (e.g. "Feel the Beat" by LB aka LABAT matching a request for Darude).

    When ``prefer_original`` is True, a small bonus (+0.1) favours results that
    look like the original version (Beatport ``mix_name`` matching "Original
    Mix"/"Extended Mix"/…) and a penalty (-0.1) is applied to results whose
    title carries a named-remix pattern (used for Tidal, which has no
    ``mix_name``). This breaks ties between "Surrender (Original Mix)" at 132
    BPM and "Surrender (Hardstyle Remix)" at 165 BPM without overriding a
    genuinely better title/artist match.

    When multiple results tie on score, a BPM-consensus tiebreaker (+0.01)
    favours the version whose BPM matches the most common BPM among all results.

    The original result object is returned unchanged, so callers can read
    provider-specific fields (key, genre, duration, cover art) off it.
    """
    logger.info(
        "find_best_match: title='%s' artist='%s' prefer_original=%s (%d results)",
        title,
        artist,
        prefer_original,
        len(results),
    )

    # Compute modal BPM for the consensus tiebreaker.
    bpm_counts: dict[int, int] = {}
    for result in results:
        bpm = get_bpm(result)
        if bpm:
            rounded = round(float(bpm))
            bpm_counts[rounded] = bpm_counts.get(rounded, 0) + 1
    modal_bpm = max(bpm_counts, key=bpm_counts.get) if bpm_counts else None

    best = None
    best_score = 0.0
    for i, result in enumerate(results):
        result_title = get_title(result)
        result_artist = get_artist(result)
        title_score = fuzzy_match_score(title, result_title)
        artist_score = artist_match_score(artist, result_artist)
        if artist_score < min_artist_score:
            logger.info(
                "  [%d] SKIP artist_score=%.3f < %.2f | title=%s artist=%s",
                i,
                artist_score,
                min_artist_score,
                result_title,
                result_artist,
            )
            continue
        combined = score_track_match(title_score, artist_score)
        version_adj = 0.0

        if prefer_original:
            mix_name = get_mix_name(result)
            if mix_name:
                # Beatport: structured mix_name available.
                if is_original_mix_name(mix_name):
                    version_adj = 0.1
                    combined += 0.1
                # Named remix/bootleg/rework in mix_name → no bonus.
            else:
                # Tidal/other: check the title for remix patterns.
                if is_remix_title(result_title):
                    version_adj = -0.1
                    combined -= 0.1

        # BPM consensus tiebreaker: prefer the modal BPM among results.
        bpm_adj = 0.0
        result_bpm = get_bpm(result)
        if modal_bpm and result_bpm and round(float(result_bpm)) == modal_bpm:
            bpm_adj = 0.01
            combined += 0.01

        logger.info(
            "  [%d] title=%s artist=%s bpm=%s mix=%s | "
            "title_sc=%.3f artist_sc=%.3f ver_adj=%+.02f bpm_adj=%+.003f => combined=%.4f",
            i,
            result_title,
            result_artist,
            result_bpm if result_bpm is not None else "?",
            get_mix_name(result) or "-",
            title_score,
            artist_score,
            version_adj,
            bpm_adj,
            combined,
        )

        if combined > best_score:
            best_score = combined
            best = result

    if best is not None and best_score >= min_score:
        logger.info(
            "  BEST: title=%s artist=%s bpm=%s (score=%.4f)",
            get_title(best),
            get_artist(best),
            get_bpm(best) if get_bpm(best) is not None else "?",
            best_score,
        )
        return best

    logger.info("  NO MATCH (best_score=%.4f < min=%.2f)", best_score, min_score)
    return None
