"""Read-time three-tier vibe precedence (issue #391): own -> community -> LLM cache.

Nothing is materialized: every read resolves each vibe field independently by
walking the tiers and taking the first non-None value, tagged with its source
for UI provenance. The viewing DJ's own vote is excluded from the community
tier (it already IS tier 1), and the LLM tier only trusts rows at the current
PROMPT_VERSION/SCHEMA_VERSION — stale cache rows stay invisible.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.set import Set
from app.models.set_pool import SetPoolTrack
from app.models.track_vibe import TrackVibe, TrackVibeOverride
from app.models.user import User
from app.services.setbuilder.community_vibe import CommunityVibe, community_consensus
from app.services.setbuilder.vibe_enrichment import PROMPT_VERSION, SCHEMA_VERSION, vibe_key
from app.services.system_settings import get_system_settings

LOW_CONFIDENCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class OwnVibe:
    energy: int | None
    mood: str | None


@dataclass(frozen=True)
class ResolvedVibe:
    energy: int | None
    energy_source: str | None  # "own" | "community" | "llm" | None
    mood: str | None
    mood_source: str | None


def is_low_confidence(vibe: TrackVibe) -> bool:
    """True when the LLM guess should be flagged for DJ review."""
    return vibe.confidence is None or vibe.confidence < LOW_CONFIDENCE_THRESHOLD


def _first(*tiers: tuple[object, str]) -> tuple[object, str | None]:
    """First non-None value walking the tiers, tagged with its source name."""
    for value, source in tiers:
        if value is not None:
            return value, source
    return None, None


def resolve_vibe(
    own: OwnVibe | None, community: CommunityVibe | None, llm: TrackVibe | None
) -> ResolvedVibe:
    """PER-FIELD cascade: energy and mood resolve independently through the tiers."""
    energy, energy_source = _first(
        (own.energy if own else None, "own"),
        (community.energy if community else None, "community"),
        (llm.energy if llm else None, "llm"),
    )
    mood, mood_source = _first(
        (own.mood if own else None, "own"),
        (community.mood if community else None, "community"),
        (llm.mood if llm else None, "llm"),
    )
    return ResolvedVibe(
        energy=energy, energy_source=energy_source, mood=mood, mood_source=mood_source
    )


@dataclass(frozen=True)
class TrackVibeState:
    pool_track_id: int
    vibe_key: str
    own: OwnVibe | None
    community: CommunityVibe | None
    llm: TrackVibe | None
    resolved: ResolvedVibe


def _own_overrides(db: Session, user_id: int, keys: list[str]) -> dict[str, OwnVibe]:
    """Latest override per track for one user; rows with both fields null count as no override."""
    unique_keys = list(dict.fromkeys(keys))
    rows = (
        db.query(TrackVibeOverride)
        .filter(TrackVibeOverride.user_id == user_id, TrackVibeOverride.track_id.in_(unique_keys))
        .order_by(TrackVibeOverride.id)
        .all()
    )
    latest: dict[str, TrackVibeOverride] = {}
    for row in rows:
        latest[row.track_id] = row  # later rows supersede earlier
    return {
        key: OwnVibe(energy=row.energy_override, mood=row.mood_override)
        for key, row in latest.items()
        if row.energy_override is not None or row.mood_override is not None
    }


def _llm_vibes(db: Session, keys: list[str]) -> dict[str, TrackVibe]:
    """Newest (highest id) current-version TrackVibe row per key — stale versions ignored."""
    unique_keys = list(dict.fromkeys(keys))
    rows = (
        db.query(TrackVibe)
        .filter(
            TrackVibe.track_id.in_(unique_keys),
            TrackVibe.prompt_version == PROMPT_VERSION,
            TrackVibe.schema_version == SCHEMA_VERSION,
        )
        .order_by(TrackVibe.id)
        .all()
    )
    newest: dict[str, TrackVibe] = {}
    for row in rows:
        newest[row.track_id] = row  # higher id wins
    return newest


def build_pool_vibe_states(db: Session, actor: User, set_obj: Set) -> list[TrackVibeState]:
    """One TrackVibeState per pool track; tracks sharing a vibe_key share their tiers."""
    tracks = (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_obj.id)
        .order_by(SetPoolTrack.id)
        .all()
    )
    if not tracks:
        return []
    keys = [vibe_key(t) for t in tracks]

    settings = get_system_settings(db)
    own = _own_overrides(db, actor.id, keys)
    community = community_consensus(
        db,
        keys,
        min_sample=settings.vibe_consensus_min_sample,
        max_stddev=settings.vibe_consensus_max_stddev,
        exclude_user_id=actor.id,
    )
    llm = _llm_vibes(db, keys)

    return [
        TrackVibeState(
            pool_track_id=track.id,
            vibe_key=key,
            own=own.get(key),
            community=community.get(key),
            llm=llm.get(key),
            resolved=resolve_vibe(own.get(key), community.get(key), llm.get(key)),
        )
        for track, key in zip(tracks, keys, strict=True)
    ]
