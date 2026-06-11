"""Community vibe consensus over TrackVibeOverride (issue #391).

Aggregates per-DJ override rows into a community signal, gated so noise never
masquerades as consensus:

- Only each user's LATEST vote per track counts (later rows supersede earlier).
- Energy consensus needs >= ``min_sample`` votes whose population stddev is
  strictly below ``max_stddev``; the value is the rounded mean.
- Mood consensus needs >= ``min_sample`` mood votes and a strict-majority
  winner (more than half of the mood votes).
- Tracks where neither field reaches consensus are omitted from the result.
- ``exclude_user_id`` drops one user's votes — the read-time resolver passes
  the viewing DJ so their own vote (precedence tier 1) never double-counts
  into the community tier they fall back to.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import fmean, pstdev

from sqlalchemy.orm import Session

from app.models.track_vibe import TrackVibeOverride


@dataclass(frozen=True)
class CommunityVibe:
    energy: int | None
    mood: str | None
    sample_size: int


def _energy_consensus(votes: list[int], min_sample: int, max_stddev: float) -> int | None:
    if not votes or len(votes) < min_sample or pstdev(votes) >= max_stddev:
        return None
    return round(fmean(votes))


def _mood_consensus(votes: list[str], min_sample: int) -> str | None:
    if not votes or len(votes) < min_sample:
        return None
    winner, count = Counter(votes).most_common(1)[0]
    return winner if count > len(votes) / 2 else None


def community_consensus(
    db: Session,
    track_keys: Iterable[str],
    *,
    min_sample: int,
    max_stddev: float,
    exclude_user_id: int | None = None,
) -> dict[str, CommunityVibe]:
    """Per-track community consensus; only tracks with >= 1 consensual field appear."""
    keys = list(track_keys)
    if not keys:
        return {}

    query = db.query(TrackVibeOverride).filter(TrackVibeOverride.track_id.in_(keys))
    if exclude_user_id is not None:
        query = query.filter(TrackVibeOverride.user_id != exclude_user_id)
    rows = query.order_by(TrackVibeOverride.id).all()

    latest: dict[tuple[str, int], TrackVibeOverride] = {}
    for row in rows:
        latest[(row.track_id, row.user_id)] = row  # later rows supersede earlier

    votes_by_track: dict[str, list[TrackVibeOverride]] = defaultdict(list)
    for row in latest.values():
        votes_by_track[row.track_id].append(row)

    result: dict[str, CommunityVibe] = {}
    for track_id, votes in votes_by_track.items():
        energy_votes = [v.energy_override for v in votes if v.energy_override is not None]
        mood_votes = [v.mood_override for v in votes if v.mood_override is not None]

        energy = _energy_consensus(energy_votes, min_sample, max_stddev)
        mood = _mood_consensus(mood_votes, min_sample)
        if energy is None and mood is None:
            continue

        result[track_id] = CommunityVibe(
            energy=energy,
            mood=mood,
            sample_size=max(len(energy_votes), len(mood_votes)),
        )
    return result
