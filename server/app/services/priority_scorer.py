"""DJ priority scoring for song requests.

Computes a composite score for each request based on:
- Vote count (crowd demand)
- Wait time (fairness)
- Harmonic key compatibility with current now-playing track
- BPM energy fit with current now-playing track

Pure-function module with no database dependencies.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.music_matching import compatibility_score, parse_key

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

DEFAULT_PRIORITY_WEIGHTS: dict[str, float] = {
    "votes": 0.35,
    "wait_time": 0.25,
    "harmonic": 0.25,
    "energy": 0.15,
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestScoreInput:
    """Input data for scoring a single request."""

    request_id: int
    vote_count: int
    created_at: datetime
    musical_key: str | None = None
    bpm: float | None = None


@dataclass(frozen=True)
class PriorityScore:
    """Computed priority score with sub-scores for transparency."""

    request_id: int
    score: float
    vote_score: float
    wait_score: float
    harmonic_score: float
    energy_score: float


# ---------------------------------------------------------------------------
# Individual scoring functions
# ---------------------------------------------------------------------------


def _score_votes(count: int, max_votes: int) -> float:
    """Score vote count using logarithmic scaling.

    Log scaling rewards early votes more heavily (0→3 matters more than 20→23).
    Returns 0.0-1.0 normalized against the max vote count in the batch.
    """
    if count <= 0 or max_votes <= 0:
        return 0.0
    return math.log(1 + count) / math.log(1 + max_votes)


def _score_wait_time(seconds_waiting: float, max_wait: float) -> float:
    """Score wait time using linear scaling.

    Older requests score higher for fairness. Clamped to [0, 1].
    """
    if max_wait <= 0 or seconds_waiting <= 0:
        return 0.0
    return min(seconds_waiting / max_wait, 1.0)


def _score_harmonic_fit(
    request_key: str | None,
    now_playing_key: str | None,
) -> float:
    """Score harmonic key compatibility with now-playing track.

    Returns 0.5 (neutral) when either key is missing, allowing
    the score to degrade gracefully to votes + time.
    """
    if request_key is None or now_playing_key is None:
        return 0.5

    request_pos = parse_key(request_key)
    now_pos = parse_key(now_playing_key)

    if request_pos is None or now_pos is None:
        return 0.5

    return compatibility_score(request_pos, now_pos)


def _score_energy_fit(
    request_bpm: float | None,
    now_playing_bpm: float | None,
) -> float:
    """Score BPM energy compatibility with now-playing track.

    1.0 within ±3 BPM, linear falloff to 0.0 at ±25 BPM.
    Half-time and double-time matches scored at 70%.
    Returns 0.5 (neutral) when either BPM is missing.
    """
    if request_bpm is None or now_playing_bpm is None:
        return 0.5

    tolerance = 3.0
    max_diff = 25.0

    diff = abs(request_bpm - now_playing_bpm)
    half_diff = abs(request_bpm - now_playing_bpm * 0.5)
    double_diff = abs(request_bpm - now_playing_bpm * 2.0)

    # Use the best (smallest) effective difference
    use_alt = False
    effective_diff = diff
    best_alt = min(half_diff, double_diff)
    if best_alt < diff:
        effective_diff = best_alt
        use_alt = True

    if effective_diff <= tolerance:
        base = 1.0
    elif effective_diff >= max_diff:
        base = 0.0
    else:
        base = 1.0 - (effective_diff - tolerance) / (max_diff - tolerance)

    if use_alt:
        return round(base * 0.7, 4)
    return round(base, 4)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------


def compute_priority_score(
    *,
    vote_count: int,
    max_votes: int,
    seconds_waiting: float,
    max_wait: float,
    request_key: str | None,
    request_bpm: float | None,
    now_playing_key: str | None,
    now_playing_bpm: float | None,
    weights: dict[str, float] | None = None,
) -> PriorityScore:
    """Compute the composite priority score for a request."""
    w = weights or DEFAULT_PRIORITY_WEIGHTS

    vote_s = _score_votes(vote_count, max_votes)
    wait_s = _score_wait_time(seconds_waiting, max_wait)
    harmonic_s = _score_harmonic_fit(request_key, now_playing_key)
    energy_s = _score_energy_fit(request_bpm, now_playing_bpm)

    total = (
        w["votes"] * vote_s
        + w["wait_time"] * wait_s
        + w["harmonic"] * harmonic_s
        + w["energy"] * energy_s
    )

    return PriorityScore(
        request_id=0,  # Caller sets this
        score=round(total, 4),
        vote_score=round(vote_s, 4),
        wait_score=round(wait_s, 4),
        harmonic_score=round(harmonic_s, 4),
        energy_score=round(energy_s, 4),
    )


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def rank_requests_by_priority(
    requests: list[RequestScoreInput],
    *,
    now_playing_key: str | None,
    now_playing_bpm: float | None,
    now: datetime | None = None,
    weights: dict[str, float] | None = None,
) -> list[PriorityScore]:
    """Score and rank requests by priority, highest first.

    Uses a stable sort so equal scores preserve original order.
    """
    if not requests:
        return []

    now = now or datetime.now(UTC)

    # Compute batch-level normalization values
    max_votes = max(r.vote_count for r in requests)

    # Handle mixed tz-aware/naive datetimes (SQLite stores naive)
    def _seconds_since(created_at: datetime) -> float:
        if created_at.tzinfo is None:
            return (now.replace(tzinfo=None) - created_at).total_seconds()
        return (now - created_at).total_seconds()

    wait_times = [_seconds_since(r.created_at) for r in requests]
    max_wait = max(wait_times) if wait_times else 0

    scored: list[PriorityScore] = []
    for req, seconds_waiting in zip(requests, wait_times):
        ps = compute_priority_score(
            vote_count=req.vote_count,
            max_votes=max_votes,
            seconds_waiting=seconds_waiting,
            max_wait=max_wait,
            request_key=req.musical_key,
            request_bpm=req.bpm,
            now_playing_key=now_playing_key,
            now_playing_bpm=now_playing_bpm,
            weights=weights,
        )
        scored.append(
            PriorityScore(
                request_id=req.request_id,
                score=ps.score,
                vote_score=ps.vote_score,
                wait_score=ps.wait_score,
                harmonic_score=ps.harmonic_score,
                energy_score=ps.energy_score,
            )
        )

    # Stable sort descending by score
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
