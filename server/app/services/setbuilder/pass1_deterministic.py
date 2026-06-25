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
from app.models.user import User
from app.services.recommendation.camelot import compatibility_score, parse_key
from app.services.recommendation.scorer import _score_bpm, _score_genre
from app.services.setbuilder import targeting
from app.services.setbuilder.curve import BUILTIN_TEMPLATES, interpolate_energy, uniform_midpoints
from app.services.setbuilder.vibe_resolver import ResolvedVibe, build_pool_vibe_states

AVG_TRACK_LENGTH_SEC = 210
MAX_SWAP_ITERATIONS = 50
PAIRING_BOOST_POINTS = 20.0

# Hard fallback cap for the generated set when no explicit ``target_duration_sec``
# is set (#538). Without this, ``_slot_count`` returned ``len(tracks)`` and a big
# pool became a multi-hour ("12-hour") set. 3 hours is the largest sane default
# short of an all-night marathon; the length gate must not depend on the DJ having
# remembered to set a target.
DEFAULT_FALLBACK_SET_DURATION_SEC = 3 * 60 * 60


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
    genre: str | None = None
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
    max_slots = _max_slot_count(pool_tracks, locked)
    # Energy targets are shaped over the upper-bound count so the curve stays
    # stable while we select; we recompute against the final count after the
    # duration-driven loop decides how many slots actually fit the target.
    targets = _target_energies(db, set_obj, max_slots)
    vibes = _pool_vibes(db, set_obj)
    metas = [_track_meta(t, vibes.get(t.id)) for t in pool_tracks]
    by_track_id = {m.slot_track_id: m for m in metas}
    # Real per-track durations (avg fallback for missing/<=0), keyed the same way
    # the chooser identifies tracks, so the loop can accumulate actual playtime.
    duration_by_track_id = {_track_meta(t).slot_track_id: _track_duration(t) for t in pool_tracks}

    target_sec = _effective_target_sec(set_obj)
    overlap_sec = max(0, int(set_obj.avg_transition_overlap_sec))
    last_locked_pos = max((slot.position for slot in locked), default=-1)

    locked_by_pos = {slot.position: slot for slot in locked if slot.position < max_slots}
    used = {slot.track_id for slot in locked_by_pos.values() if slot.track_id}
    chosen: list[TrackMeta | None] = []
    total_sec = 0
    for pos in range(max_slots):
        locked_slot = locked_by_pos.get(pos)
        if locked_slot is not None:
            meta = by_track_id.get(locked_slot.track_id or "")
            chosen.append(meta)
            if meta is not None:
                total_sec += duration_by_track_id.get(meta.slot_track_id, AVG_TRACK_LENGTH_SEC)
        else:
            candidate = _best_candidate(
                metas=metas,
                used=used,
                previous=_previous_track(chosen),
                selected=chosen,
                position=pos,
                slot_count=max_slots,
                target_energy=targets[pos],
                key_strictness=set_obj.key_strictness,
                pairings=pairings,
            )
            chosen.append(candidate)
            if candidate is not None:
                used.add(candidate.slot_track_id)
                total_sec += duration_by_track_id.get(candidate.slot_track_id, AVG_TRACK_LENGTH_SEC)
        # Stop once the accumulated, overlap-discounted effective playtime reaches
        # the target — but never before the last locked slot, which must survive.
        effective = targeting.effective_duration_sec(total_sec, len(chosen), overlap_sec)
        if pos >= last_locked_pos and effective >= target_sec:
            break

    chosen = _trim_trailing_unfilled(chosen, last_locked_pos)
    slot_count = len(chosen)
    targets = _target_energies(db, set_obj, slot_count)

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
    vibes = _pool_vibes(db, set_obj)
    pool_metas = [_track_meta(t, vibes.get(t.id)) for t in _pool_tracks(db, set_obj.id)]
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


def _track_meta(track: SetPoolTrack, resolved: ResolvedVibe | None = None) -> TrackMeta:
    """Build a scoring meta for a pool track.

    Energy and mood are sourced from the read-time vibe cascade (own > community
    > LLM, #391) when ``resolved`` is supplied — the pool row's own ``energy``/
    ``mood`` are structurally ``None`` in production (no import fills them), so
    without this overlay the builder's ``0.30 * _energy_match`` and mood terms
    are dead constants (#543). The pool row remains the fallback so callers that
    pass no resolved vibe (and any row that does carry its own value) still work.

    ``genre`` is sourced straight off the pool row (#545) — it is a guaranteed
    contract field hydrated from the global ``tracks`` row on upsert, NOT part of
    the vibe cascade (which only carries energy/mood), so it reads like bpm/key
    rather than via ``resolved``. Missing genre stays ``None`` and degrades
    neutrally in ``_genre_continuity``.

    ``transitional_role`` has no resolver source yet — the cascade only carries
    energy/mood — so its scoring term stays a neutral constant (see ``_role_fit``
    TODO). Re-point energy/mood at the global ``tracks`` row when that lands.
    """
    energy = track.energy
    mood = None
    if resolved is not None:
        if resolved.energy is not None:
            energy = resolved.energy
        mood = resolved.mood
    return TrackMeta(
        pool_id=track.id,
        slot_track_id=track.track_id or f"pool:{track.id}",
        title=track.title,
        artist=track.artist,
        bpm=track.bpm,
        key=track.camelot or track.key,
        energy=energy,
        mood=mood,
        genre=track.genre,
    )


def _pool_vibes(db: Session, set_obj: Set) -> dict[int, ResolvedVibe]:
    """Resolve each pool track's vibe (own > community > LLM) keyed by pool id.

    The cascade needs the acting DJ; the build path only carries ``(db, set_obj)``,
    so the owner is resolved the same way the agent import tools do
    (``db.get(User, set_obj.owner_id)``). Missing owner degrades neutrally to an
    empty map — the builder then falls back to pool-row values (all ``None`` in
    prod), i.e. exactly the pre-#543 behavior, never a crash.
    """
    owner = db.get(User, set_obj.owner_id)
    if owner is None:
        return {}
    states = build_pool_vibe_states(db, owner, set_obj)
    return {state.pool_track_id: state.resolved for state in states}


def _effective_target_sec(set_obj: Set) -> int:
    """The duration the generated set is built toward.

    The set's explicit ``target_duration_sec`` when set, otherwise the hard
    fallback cap (#538) so an unset target never dumps the whole pool. A
    non-positive explicit target also falls back to the cap.
    """
    target = set_obj.target_duration_sec
    if target and target > 0:
        return int(target)
    return DEFAULT_FALLBACK_SET_DURATION_SEC


def _track_duration(track: SetPoolTrack) -> int:
    """A pool track's real duration in seconds, with the avg fallback for
    missing/non-positive values — matching what the build budgets against."""
    if track.duration_sec and track.duration_sec > 0:
        return int(track.duration_sec)
    return AVG_TRACK_LENGTH_SEC


def _max_slot_count(tracks: list[SetPoolTrack], locked: list[SetSlot]) -> int:
    """Hard upper bound on the selection loop — the pool size, floored to cover
    every locked position (#538).

    This is *only* the loop's ceiling, not the target. Where the loop actually
    stops is decided inside ``build_set`` by accumulating real track durations
    against ``_effective_target_sec`` (which carries the 3-hour fallback cap), so
    the set is length-gated by effective playtime, never by an average-duration
    estimate. Deriving this bound from the *average* duration was unsound: a pool
    whose selected prefix runs shorter than average (e.g. one long outlier skewing
    the mean up) would exhaust the range and undershoot the target while
    candidates remained. The duration loop + cap make the pool size a safe bound —
    a no-target build still stops at the 3h cap long before exhausting a big pool.
    """
    desired = max(len(tracks), len(locked))
    if locked:
        desired = max(desired, max(slot.position for slot in locked) + 1)
    return max(0, desired)


def _trim_trailing_unfilled(
    chosen: list[TrackMeta | None], last_locked_pos: int
) -> list[TrackMeta | None]:
    """Drop trailing positions the pool couldn't fill (``None``), but never trim
    past the last locked position, which must keep its slot even if empty."""
    end = len(chosen)
    while end - 1 > last_locked_pos and chosen[end - 1] is None:
        end -= 1
    return chosen[:end]


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
    # Genre (#545) is funded by halving the role term (0.10->0.05, a neutral
    # constant today with no resolver source) and the mood term (0.10->0.05, the
    # weakest live signal); the dominant energy/bpm/key terms are untouched, so
    # existing ordering is preserved and all terms still sum to 1.00.
    score = (
        0.30 * _energy_match(candidate.energy, target_energy)
        + 0.25 * _bpm_continuity(previous, candidate)
        + 0.20 * _camelot_continuity(previous, candidate, key_strictness)
        + 0.10 * _genre_continuity(previous, candidate)
        + 0.05 * _role_fit(candidate.transitional_role, position, slot_count, target_energy)
        + 0.05 * _mood_continuity(previous, candidate)
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


def _genre_continuity(previous: TrackMeta | None, current: TrackMeta) -> float:
    """Reward staying within / smoothly moving between related genres (#545).

    Delegates to the recommendation scorer's curated genre affinity
    (``_score_genre``: exact 1.0 / substring 0.5 / same-family 0.4 / related
    family 0.2-0.4 / unrelated 0.0) by treating the previous track's genre as a
    single-element dominant-genre lane — DRY, no second genre taxonomy.

    Degrades neutrally to ``0.5`` (the no-information midpoint used by the other
    ``_*_continuity`` helpers) at the set start or when either side has no genre
    — including whitespace-only genres, which the pool import stores verbatim —
    so a missing-genre track is never penalized.
    """
    previous_genre = previous.genre.strip() if previous and previous.genre else ""
    current_genre = current.genre.strip() if current.genre else ""
    if not previous_genre or not current_genre:
        return 0.5
    return _score_genre(current_genre, [previous_genre])


def _role_fit(role: str | None, position: int, slot_count: int, target: float) -> float:
    # TODO(#543): ``transitional_role`` has no resolver source — the vibe cascade
    # (own > community > LLM) surfaces only energy/mood, never role. TrackMeta.
    # transitional_role is therefore always None today, so this term is a neutral
    # 0.5 constant. The scoring logic below is kept (not deleted) so the term goes
    # live for free once a role source is wired (e.g. via the global tracks row or
    # an extended cascade); deleting it would silently re-weight the other terms
    # and collide with the genre work in #545.
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
        # Agent path (autobuild): flush so _ordered_slots sees the new rows, but
        # leave the transaction open so the chat turn owns the commit/rollback.
        db.flush()
    return _ordered_slots(db, set_id)
