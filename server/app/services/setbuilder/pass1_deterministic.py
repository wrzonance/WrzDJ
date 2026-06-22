"""Deterministic WrzDJSet builder pass (#390).

Pass 1 turns the pool plus the set's energy targets into an ordered timeline.
The algorithm is intentionally deterministic: stable input ordering, no random
tie-breakers, greedy fill first, then a capped 2-opt-style swap refinement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolTrack
from app.services.recommendation.camelot import compatibility_score, parse_key
from app.services.recommendation.scorer import _score_bpm
from app.services.setbuilder.curve import BUILTIN_TEMPLATES, interpolate_energy, uniform_midpoints

AVG_TRACK_LENGTH_SEC = 210
MAX_SWAP_ITERATIONS = 50
PAIRING_BOOST_POINTS = 20.0


@dataclass(frozen=True)
class TrackMeta:
    pool_id: int
    slot_track_id: str
    title: str
    artist: str
    bpm: float | None
    key: str | None
    energy: int | None
    mood: str | None = None
    transitional_role: str | None = None


@dataclass(frozen=True)
class TransitionScore:
    slot_id: int
    position: int
    score: float
    warnings: list[str]


@dataclass(frozen=True)
class BuildResult:
    slots: list[SetSlot]
    slot_count: int
    iterations: int
    transition_scores: list[TransitionScore]


def build_set(db: Session, set_obj: Set, *, commit: bool = True) -> BuildResult:
    """Build and persist a deterministic ordered set from the set pool."""
    pool_tracks = _pool_tracks(db, set_obj.id)
    locked = _locked_slots(db, set_obj.id)
    pairings = _saved_pairings(db, set_obj.id)
    slot_count = _slot_count(set_obj, pool_tracks, locked)
    targets = _target_energies(db, set_obj, slot_count)
    metas = [_track_meta(t) for t in pool_tracks]
    by_track_id = {m.slot_track_id: m for m in metas}

    locked_by_pos = {slot.position: slot for slot in locked if slot.position < slot_count}
    used = {slot.track_id for slot in locked_by_pos.values() if slot.track_id}
    chosen: list[TrackMeta | None] = []
    for pos in range(slot_count):
        locked_slot = locked_by_pos.get(pos)
        if locked_slot is not None:
            chosen.append(by_track_id.get(locked_slot.track_id or ""))
            continue
        prev = _previous_track(chosen)
        candidate = _best_candidate(
            metas=metas,
            used=used,
            previous=prev,
            selected=chosen,
            position=pos,
            slot_count=slot_count,
            target_energy=targets[pos],
            key_strictness=set_obj.key_strictness,
            pairings=pairings,
        )
        chosen.append(candidate)
        if candidate is not None:
            used.add(candidate.slot_track_id)

    chosen, iterations = _refine_swaps(
        chosen=chosen,
        locked_positions=set(locked_by_pos),
        targets=targets,
        key_strictness=set_obj.key_strictness,
    )
    slots = _persist_slots(db, set_obj.id, locked_by_pos, chosen, targets, commit=commit)
    scores = recompute_transition_scores(db, set_obj, slots, commit=commit)
    return BuildResult(
        slots=slots,
        slot_count=slot_count,
        iterations=iterations,
        transition_scores=scores,
    )


def recompute_transition_scores(
    db: Session,
    set_obj: Set,
    slots: list[SetSlot] | None = None,
    affected_positions: set[int] | None = None,
    *,
    commit: bool = True,
) -> list[TransitionScore]:
    """Recompute transition scores for all or affected slots, honoring current order."""
    if slots is None:
        slots = _ordered_slots(db, set_obj.id)
    pool_metas = [_track_meta(t) for t in _pool_tracks(db, set_obj.id)]
    tracks_by_id = {meta.slot_track_id: meta for meta in pool_metas}
    scores: list[TransitionScore] = []
    for idx, slot in enumerate(slots):
        if affected_positions is not None and slot.position not in affected_positions:
            continue
        previous = slots[idx - 1] if idx > 0 else None
        prev_meta = tracks_by_id.get(previous.track_id or "") if previous else None
        curr_meta = tracks_by_id.get(slot.track_id or "")
        if idx == 0 or curr_meta is None:
            score = 100.0 if idx == 0 and curr_meta is not None else 0.0
            warnings = [] if curr_meta is not None else ["missing_pool_metadata"]
        else:
            score, warnings = transition_score(prev_meta, curr_meta, set_obj.key_strictness)
        slot.transition_score = score
        slot.transition_warnings = json.dumps(warnings)
        scores.append(
            TransitionScore(slot_id=slot.id, position=slot.position, score=score, warnings=warnings)
        )
    if commit:
        db.commit()
    else:
        db.flush()
    return scores


def transition_score(
    previous: TrackMeta | None,
    current: TrackMeta,
    key_strictness: float,
) -> tuple[float, list[str]]:
    """Score one transition on a 0-100 scale."""
    bpm = _bpm_continuity(previous, current)
    key = _camelot_continuity(previous, current, key_strictness)
    mood = _mood_continuity(previous, current)
    artist = 0.0 if previous and _same_artist(previous.artist, current.artist) else 1.0
    score = round((0.35 * bpm + 0.30 * key + 0.20 * mood + 0.15 * artist) * 100, 2)
    warnings = []
    if bpm < 0.45:
        warnings.append("bpm_jump")
    if key < 0.35:
        warnings.append("key_clash")
    if mood < 0.4:
        warnings.append("mood_shift")
    if artist == 0.0:
        warnings.append("repeat_artist")
    return score, warnings


def _pool_tracks(db: Session, set_id: int) -> list[SetPoolTrack]:
    return (
        db.query(SetPoolTrack)
        .filter(SetPoolTrack.set_id == set_id)
        .order_by(SetPoolTrack.id.asc())
        .all()
    )


def _ordered_slots(db: Session, set_id: int) -> list[SetSlot]:
    return db.query(SetSlot).filter(SetSlot.set_id == set_id).order_by(SetSlot.position.asc()).all()


def _locked_slots(db: Session, set_id: int) -> list[SetSlot]:
    return (
        db.query(SetSlot)
        .filter(SetSlot.set_id == set_id, SetSlot.locked == True)  # noqa: E712
        .order_by(SetSlot.position.asc())
        .all()
    )


def _saved_pairings(db: Session, set_id: int) -> set[tuple[str, str]]:
    slots = _ordered_slots(db, set_id)
    pairings: set[tuple[str, str]] = set()
    for prev, curr in zip(slots, slots[1:]):
        if prev.track_id and curr.track_id:
            pairings.add((prev.track_id, curr.track_id))
    return pairings


def _track_meta(track: SetPoolTrack) -> TrackMeta:
    return TrackMeta(
        pool_id=track.id,
        slot_track_id=track.track_id or f"pool:{track.id}",
        title=track.title,
        artist=track.artist,
        bpm=track.bpm,
        key=track.camelot or track.key,
        energy=track.energy,
    )


def _slot_count(set_obj: Set, tracks: list[SetPoolTrack], locked: list[SetSlot]) -> int:
    if set_obj.target_duration_sec:
        avg = _average_duration(tracks)
        desired = max(1, round(set_obj.target_duration_sec / avg))
    else:
        desired = len(tracks)
    desired = min(desired, max(len(tracks), len(locked)))
    if locked:
        desired = max(desired, max(slot.position for slot in locked) + 1)
    return max(0, desired)


def _average_duration(tracks: list[SetPoolTrack]) -> int:
    durations = [t.duration_sec for t in tracks if t.duration_sec and t.duration_sec > 0]
    if not durations:
        return AVG_TRACK_LENGTH_SEC
    return max(1, round(sum(durations) / len(durations)))


def _target_energies(db: Session, set_obj: Set, slot_count: int) -> list[float]:
    existing = {
        slot.position: slot.target_energy
        for slot in _ordered_slots(db, set_obj.id)
        if slot.target_energy is not None
    }
    points = BUILTIN_TEMPLATES["Open-Format"]
    midpoints = uniform_midpoints(slot_count) if slot_count else []
    return [
        round(existing[pos], 1)
        if pos in existing
        else round(interpolate_energy(points, midpoints[pos]), 1)
        for pos in range(slot_count)
    ]


def _previous_track(chosen: list[TrackMeta | None]) -> TrackMeta | None:
    for track in reversed(chosen):
        if track is not None:
            return track
    return None


def _best_candidate(
    *,
    metas: list[TrackMeta],
    used: set[str],
    previous: TrackMeta | None,
    selected: list[TrackMeta | None],
    position: int,
    slot_count: int,
    target_energy: float,
    key_strictness: float,
    pairings: set[tuple[str, str]],
) -> TrackMeta | None:
    available = [m for m in metas if m.slot_track_id not in used]
    if not available:
        return None
    return max(
        available,
        key=lambda m: (
            _candidate_score(
                m,
                previous,
                selected,
                position,
                slot_count,
                target_energy,
                key_strictness,
                pairings,
            ),
            -m.pool_id,
        ),
    )


def _candidate_score(
    candidate: TrackMeta,
    previous: TrackMeta | None,
    selected: list[TrackMeta | None],
    position: int,
    slot_count: int,
    target_energy: float,
    key_strictness: float,
    pairings: set[tuple[str, str]],
) -> float:
    score = (
        0.30 * _energy_match(candidate.energy, target_energy)
        + 0.25 * _bpm_continuity(previous, candidate)
        + 0.20 * _camelot_continuity(previous, candidate, key_strictness)
        + 0.10 * _role_fit(candidate.transitional_role, position, slot_count, target_energy)
        + 0.10 * _mood_continuity(previous, candidate)
        + 0.05 * _artist_diversity(candidate, selected)
    ) * 100
    if previous and (previous.slot_track_id, candidate.slot_track_id) in pairings:
        score += PAIRING_BOOST_POINTS
    return round(score, 4)


def _energy_match(energy: int | None, target: float) -> float:
    if energy is None:
        return 0.5
    return max(0.0, 1.0 - abs(float(energy) - target) / 10.0)


def _bpm_continuity(previous: TrackMeta | None, current: TrackMeta) -> float:
    if previous is None:
        return 0.75
    return _score_bpm(current.bpm, previous.bpm)


def _camelot_continuity(previous: TrackMeta | None, current: TrackMeta, strictness: float) -> float:
    if previous is None:
        return 0.75
    compat = compatibility_score(parse_key(previous.key), parse_key(current.key))
    neutral = 0.5
    return neutral + (compat - neutral) * max(0.0, min(1.0, strictness))


def _mood_continuity(previous: TrackMeta | None, current: TrackMeta) -> float:
    if previous is None or not previous.mood or not current.mood:
        return 0.5
    return 1.0 if previous.mood.strip().lower() == current.mood.strip().lower() else 0.35


def _role_fit(role: str | None, position: int, slot_count: int, target: float) -> float:
    if not role:
        return 0.5
    normalized = role.strip().lower().replace("-", "_").replace(" ", "_")
    t = 0.0 if slot_count <= 1 else position / (slot_count - 1)
    if normalized in {"opener", "intro", "warmup", "warm_up"}:
        return max(0.0, 1.0 - t)
    if normalized in {"closer", "closing"}:
        return t
    if normalized in {"banger", "peak", "anthem"}:
        return min(1.0, target / 8.0)
    if normalized in {"bridge", "transition", "breather"}:
        return 1.0 - abs(target - 5.0) / 5.0
    return 0.5


def _artist_diversity(candidate: TrackMeta, selected: list[TrackMeta | None]) -> float:
    recent = [t for t in selected[-3:] if t is not None]
    if any(_same_artist(t.artist, candidate.artist) for t in recent):
        return 0.0
    if any(t is not None and _same_artist(t.artist, candidate.artist) for t in selected):
        return 0.5
    return 1.0


def _same_artist(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def _refine_swaps(
    *,
    chosen: list[TrackMeta | None],
    locked_positions: set[int],
    targets: list[float],
    key_strictness: float,
) -> tuple[list[TrackMeta | None], int]:
    current = list(chosen)
    iterations = 0
    while iterations < MAX_SWAP_ITERATIONS:
        worst = _worst_transition_index(current, key_strictness)
        if worst is None:
            break
        pivot = worst if worst not in locked_positions else worst - 1
        if pivot < 0 or pivot in locked_positions or current[pivot] is None:
            break
        base = _overall_score(current, key_strictness)
        accepted = False
        for other in range(pivot + 1, len(current)):
            if other in locked_positions or current[other] is None:
                continue
            trial = list(current)
            trial[pivot], trial[other] = trial[other], trial[pivot]
            improved = _overall_score(trial, key_strictness)
            if improved > base + 0.001:
                current = trial
                accepted = True
                break
        iterations += 1
        if not accepted:
            break
    return current, iterations


def _worst_transition_index(chosen: list[TrackMeta | None], key_strictness: float) -> int | None:
    worst_idx = None
    worst_score = 101.0
    for idx in range(1, len(chosen)):
        prev = chosen[idx - 1]
        curr = chosen[idx]
        if prev is None or curr is None:
            continue
        score, _ = transition_score(prev, curr, key_strictness)
        if score < worst_score:
            worst_score = score
            worst_idx = idx
    return worst_idx


def _overall_score(chosen: list[TrackMeta | None], key_strictness: float) -> float:
    scores = []
    for prev, curr in zip(chosen, chosen[1:]):
        if prev is not None and curr is not None:
            score, _ = transition_score(prev, curr, key_strictness)
            scores.append(score)
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _persist_slots(
    db: Session,
    set_id: int,
    locked_by_pos: dict[int, SetSlot],
    chosen: list[TrackMeta | None],
    targets: list[float],
    *,
    commit: bool = True,
) -> list[SetSlot]:
    for slot in (
        db.query(SetSlot)
        .filter(SetSlot.set_id == set_id, SetSlot.locked == False)  # noqa: E712
        .all()
    ):
        db.delete(slot)
    db.flush()

    for pos, track in enumerate(chosen):
        locked = locked_by_pos.get(pos)
        if locked is not None:
            locked.target_energy = targets[pos]
            continue
        if track is None:
            continue
        db.add(
            SetSlot(
                set_id=set_id,
                position=pos,
                track_id=track.slot_track_id,
                locked=False,
                target_energy=targets[pos],
            )
        )
    if commit:
        db.commit()
    else:
        db.flush()
    return _ordered_slots(db, set_id)
