"""Recommendation-specific profiles and candidate ranking.

Combines shared musical compatibility primitives with event-profile data to
rank candidates for an event.
"""

from collections import Counter
from dataclasses import dataclass, field

from app.services.music_matching import (
    compatibility_score,
    parse_key,
    score_bpm,
    score_genre,
)
from app.services.tracks.profile import TrackProfile


@dataclass(frozen=True)
class EventProfile:
    """Musical profile of an event built from its requests."""

    avg_bpm: float | None = None
    bpm_range: tuple[float, float] | None = None
    dominant_keys: list[str] = field(default_factory=list)
    dominant_genres: list[str] = field(default_factory=list)
    track_count: int = 0


@dataclass(frozen=True)
class ScoredTrack:
    """A candidate track with its computed scores."""

    profile: TrackProfile
    score: float
    bpm_score: float
    key_score: float
    genre_score: float


DEFAULT_WEIGHTS: dict[str, float] = {"bpm": 0.40, "key": 0.40, "genre": 0.20}


def build_event_profile(tracks: list[TrackProfile]) -> EventProfile:
    """Build an EventProfile from a list of enriched tracks.

    Computes average BPM, BPM range, dominant keys (top 3),
    and dominant genres (top 3).
    """
    if not tracks:
        return EventProfile(track_count=0)

    bpms = [t.bpm for t in tracks if t.bpm is not None]
    keys = [t.key for t in tracks if t.key]
    genres = [t.genre for t in tracks if t.genre]

    avg_bpm = sum(bpms) / len(bpms) if bpms else None
    bpm_range = (min(bpms), max(bpms)) if bpms else None

    # Top 3 most common keys and genres
    dominant_keys = [k for k, _ in Counter(keys).most_common(3)]
    dominant_genres = [g for g, _ in Counter(genres).most_common(3)]

    return EventProfile(
        avg_bpm=avg_bpm,
        bpm_range=bpm_range,
        dominant_keys=dominant_keys,
        dominant_genres=dominant_genres,
        track_count=len(tracks),
    )


def _score_key(
    candidate_key: str | None,
    dominant_keys: list[str],
) -> float:
    """Score key compatibility against dominant keys.

    Returns the best compatibility score against any dominant key.
    0.5 if candidate key is missing.
    """
    if not candidate_key:
        return 0.5

    candidate_pos = parse_key(candidate_key)
    if candidate_pos is None:
        return 0.5

    if not dominant_keys:
        return 0.5

    best = 0.0
    for dk in dominant_keys:
        dk_pos = parse_key(dk)
        score = compatibility_score(candidate_pos, dk_pos)
        if score > best:
            best = score
    return best


def _compute_weights(event_profile: EventProfile) -> dict[str, float]:
    """Compute dynamic weights based on available data.

    If no genre data, redistribute: BPM 0.50, key 0.50, genre 0.0.
    """
    if not event_profile.dominant_genres:
        return {"bpm": 0.50, "key": 0.50, "genre": 0.0}
    return dict(DEFAULT_WEIGHTS)


def score_candidate(
    candidate: TrackProfile,
    event_profile: EventProfile,
    weights: dict[str, float] | None = None,
) -> ScoredTrack:
    """Score a single candidate track against an event profile.

    Uses dimension-normalized scoring: only dimensions where the candidate
    has real data contribute to the final score. This prevents tracks with
    more complete metadata (e.g. Beatport with genre) from scoring higher
    than tracks with less metadata (e.g. Tidal without genre) when their
    actual musical compatibility is equivalent.
    """
    if weights is None:
        weights = _compute_weights(event_profile)

    bpm_s = score_bpm(candidate.bpm, event_profile.avg_bpm)
    key_s = _score_key(candidate.key, event_profile.dominant_keys)
    genre_s = score_genre(candidate.genre, event_profile.dominant_genres)

    # Dimension-normalized scoring: only include dimensions where the
    # candidate has real data. This eliminates the metadata-completeness
    # bias where Beatport tracks (with genre) score higher than Tidal
    # tracks (without genre) despite equal musical compatibility.
    has_bpm = candidate.bpm is not None and event_profile.avg_bpm is not None
    has_key = candidate.key is not None and bool(event_profile.dominant_keys)
    has_genre = candidate.genre is not None and bool(event_profile.dominant_genres)

    active_weight = 0.0
    total = 0.0
    if has_bpm:
        total += weights["bpm"] * bpm_s
        active_weight += weights["bpm"]
    if has_key:
        total += weights["key"] * key_s
        active_weight += weights["key"]
    if has_genre:
        total += weights["genre"] * genre_s
        active_weight += weights["genre"]

    # Normalize to 0-1 range based on active dimensions
    if active_weight > 0:
        total = total / active_weight
    else:
        # No scorable dimensions — use neutral score
        total = 0.5

    return ScoredTrack(
        profile=candidate,
        score=round(total, 4),
        bpm_score=round(bpm_s, 4),
        key_score=round(key_s, 4),
        genre_score=round(genre_s, 4),
    )


def rank_candidates(
    candidates: list[TrackProfile],
    event_profile: EventProfile,
    max_results: int = 20,
) -> list[ScoredTrack]:
    """Score and rank candidates, returning top N by score descending."""
    if not candidates:
        return []

    weights = _compute_weights(event_profile)
    scored = [score_candidate(c, event_profile, weights) for c in candidates]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:max_results]
