"""Per-DJ taste profile derived from TrackVibeOverride history (#409)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.set_taste_profile import SetTasteProfileReset
from app.models.track_vibe import TRACK_VIBE_SOURCE_EXPLICIT_EDIT, TrackVibeOverride
from app.services.setbuilder.vibe_resolver import ResolvedVibe

MIN_TASTE_SAMPLES = 5
MAX_PROFILE_ROWS = 250
ENERGY_ADJUSTMENT_CAP = 1.5
TOP_MOOD_LIMIT = 3


@dataclass(frozen=True)
class TasteMood:
    mood: str
    count: int


@dataclass(frozen=True)
class TasteProfile:
    sample_count: int
    min_samples: int
    active: bool
    average_energy_delta: float | None
    energy_adjustment: float
    top_moods: list[TasteMood]
    summary: str
    reset_at: datetime | None


def build_taste_profile(db: Session, user_id: int) -> TasteProfile:
    """Compute the current DJ's taste profile from recent explicit vibe edits."""
    reset = _latest_reset(db, user_id)
    rows = _training_rows(db, user_id, reset.reset_at if reset else None)
    deltas = [
        float(row.energy_override - row.energy_was)
        for row in rows
        if row.energy_override is not None
        and row.energy_was is not None
        and row.energy_override != row.energy_was
    ]
    sample_count = len(deltas)
    average_delta = round(sum(deltas) / sample_count, 2) if deltas else None
    active = sample_count >= MIN_TASTE_SAMPLES
    adjustment = _cap(average_delta or 0.0) if active else 0.0
    moods = _top_moods(rows)
    return TasteProfile(
        sample_count=sample_count,
        min_samples=MIN_TASTE_SAMPLES,
        active=active,
        average_energy_delta=average_delta,
        energy_adjustment=adjustment,
        top_moods=moods,
        summary=_summary(sample_count, active, adjustment, moods),
        reset_at=reset.reset_at if reset else None,
    )


def reset_taste_profile(db: Session, user_id: int) -> TasteProfile:
    """Store a reset marker and return the now-current read-time profile."""
    db.add(SetTasteProfileReset(user_id=user_id, reset_at=utcnow()))
    db.commit()
    return build_taste_profile(db, user_id)


def taste_adjusted_energy(
    resolved: ResolvedVibe,
    profile: TasteProfile | None,
) -> float | None:
    """Apply the active profile's capped energy calibration to a resolved vibe value."""
    if resolved.energy is None:
        return None
    if (
        resolved.energy_source == "own"
        or profile is None
        or not profile.active
        or profile.energy_adjustment == 0
    ):
        return float(resolved.energy)
    return round(max(0.0, min(10.0, float(resolved.energy) + profile.energy_adjustment)), 2)


def profile_context(profile: TasteProfile | None) -> dict:
    """Compact JSON-safe profile summary for pass-2 agent context."""
    if profile is None:
        return {
            "active": False,
            "sample_count": 0,
            "min_samples": MIN_TASTE_SAMPLES,
            "energy_adjustment": 0.0,
            "top_moods": [],
            "summary": "Taste profile unavailable.",
        }
    return {
        "active": profile.active,
        "sample_count": profile.sample_count,
        "min_samples": profile.min_samples,
        "energy_adjustment": profile.energy_adjustment,
        "top_moods": [{"mood": mood.mood, "count": mood.count} for mood in profile.top_moods],
        "summary": profile.summary,
    }


def _latest_reset(db: Session, user_id: int) -> SetTasteProfileReset | None:
    return (
        db.query(SetTasteProfileReset)
        .filter(SetTasteProfileReset.user_id == user_id)
        .order_by(SetTasteProfileReset.reset_at.desc(), SetTasteProfileReset.id.desc())
        .first()
    )


def _training_rows(
    db: Session,
    user_id: int,
    reset_at: datetime | None,
) -> list[TrackVibeOverride]:
    filters = [
        TrackVibeOverride.user_id == user_id,
        TrackVibeOverride.source == TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
        or_(
            and_(
                TrackVibeOverride.energy_override != None,
                TrackVibeOverride.energy_was != None,
            ),
            TrackVibeOverride.mood_override != None,
        ),
    ]
    if reset_at is not None:
        filters.append(TrackVibeOverride.created_at > reset_at)
    return (
        db.query(TrackVibeOverride)
        .filter(*filters)
        .order_by(TrackVibeOverride.created_at.desc(), TrackVibeOverride.id.desc())
        .limit(MAX_PROFILE_ROWS)
        .all()
    )


def _top_moods(rows: list[TrackVibeOverride]) -> list[TasteMood]:
    display_by_key: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        mood = (row.mood_override or "").strip()
        if not mood:
            continue
        previous_mood = (row.mood_was or "").strip()
        if previous_mood and mood.casefold() == previous_mood.casefold():
            continue
        key = mood.lower()
        display_by_key.setdefault(key, mood)
        counts[key] += 1
    return [
        TasteMood(mood=display_by_key[key], count=count)
        for key, count in counts.most_common(TOP_MOOD_LIMIT)
    ]


def _summary(
    sample_count: int,
    active: bool,
    adjustment: float,
    moods: list[TasteMood],
) -> str:
    if sample_count == 0:
        return "No learned taste profile yet."
    mood_text = _mood_summary(moods)
    if not active:
        return (
            f"Learning from {sample_count}/{MIN_TASTE_SAMPLES} energy edits; "
            f"no scoring adjustment yet{mood_text}."
        )
    return f"Learned from {sample_count} energy edits: energy {adjustment:+.1f}{mood_text}."


def _mood_summary(moods: list[TasteMood]) -> str:
    if not moods:
        return ""
    joined = ", ".join(f"{mood.mood} ({mood.count})" for mood in moods)
    return f"; top moods {joined}"


def _cap(value: float) -> float:
    return round(max(-ENERGY_ADJUSTMENT_CAP, min(ENERGY_ADJUSTMENT_CAP, value)), 1)
