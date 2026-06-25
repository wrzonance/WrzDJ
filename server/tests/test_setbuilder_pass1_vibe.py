"""Regression tests: pass-1 must score on RESOLVED vibe energy/mood (#543).

Before #543 the deterministic builder read ``energy``/``mood`` straight off the
``SetPoolTrack`` row, which is structurally always ``None`` in production (no
import source fills it; LLM-inferred energy lives in the ``TrackVibe`` cache and
was only resolved read-time for the UI). So the ``0.30 * _energy_match`` term was
a constant and the energy curve had nothing to match against.

These tests seed the realistic production shape — pool rows with ``energy=None``,
energy living only in the LLM ``TrackVibe`` cache — and assert the builder now
threads resolved energy into candidate scoring so the per-slot ``target_energy``
curve actually drives selection.
"""

from sqlalchemy.orm import Session

from app.models.set import Set
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.track_vibe import TrackVibe
from app.models.user import User
from app.services.setbuilder.curve import BUILTIN_TEMPLATES, interpolate_energy, uniform_midpoints
from app.services.setbuilder.pass1_deterministic import _pool_vibes, build_set
from app.services.setbuilder.vibe_enrichment import PROMPT_VERSION, SCHEMA_VERSION


def _mk_set(db: Session, user: User, *, duration: int) -> Set:
    set_obj = Set(owner_id=user.id, name="Vibe-driven", target_duration_sec=duration)
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _mk_source(db: Session, set_obj: Set) -> SetPoolSource:
    src = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _mk_track(db: Session, set_obj: Set, source: SetPoolSource, idx: int, **kw) -> SetPoolTrack:
    """Pool track with energy LEFT NULL — mirrors production (no import fills it)."""
    defaults = dict(
        set_id=set_obj.id,
        source_id=source.id,
        track_id=f"tidal:{idx}",
        title=f"Track {idx}",
        artist=f"Artist {idx}",
        bpm=124.0,
        key="8A",
        camelot="8A",
        energy=None,  # structurally None in prod
        duration_sec=210,
        dedupe_sig=f"sig-{idx}",
    )
    defaults.update(kw)
    track = SetPoolTrack(**defaults)
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def _llm_energy(db: Session, track_id: str, *, energy: int, mood: str | None = None) -> None:
    """Seed a current-version global LLM vibe row (the resolver's tier-3 source)."""
    db.add(
        TrackVibe(
            track_id=track_id,
            energy=energy,
            mood=mood,
            confidence=0.9,
            llm_provider="anthropic_apikey",
            llm_model="claude-haiku-4-5",
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
        )
    )
    db.commit()


def test_resolved_energy_breaks_tie_toward_slot_target(db: Session, test_user: User):
    """Two otherwise-identical candidates compete for slot 0; the one whose RESOLVED
    energy is closer to that slot's target_energy must win.

    Before #543 both candidates scored identically (energy term constant on
    pool-row None) and the deterministic tie-break ``-pool_id`` would pick the
    LOWER pool_id. We arrange the energy-correct track to have the HIGHER pool_id
    so the *only* way it can win is the now-live energy term — making this a true
    regression test that would have failed before the fix.
    """
    set_obj = _mk_set(db, test_user, duration=210)  # one slot
    src = _mk_source(db, set_obj)

    # Determine slot 0's target on the default Open-Format curve.
    points = BUILTIN_TEMPLATES["Open-Format"]
    target = round(interpolate_energy(points, uniform_midpoints(1)[0]), 1)

    far = max(0, min(10, round(target) - 4))
    near = max(0, min(10, round(target)))
    assert far != near, "fixture needs distinguishable energies"

    # Lower pool_id = the FAR-from-target track (would win the -pool_id tie-break).
    far_track = _mk_track(db, set_obj, src, 0, track_id="tidal:far")
    near_track = _mk_track(db, set_obj, src, 1, track_id="tidal:near")
    assert far_track.id < near_track.id

    _llm_energy(db, "tidal:far", energy=far)
    _llm_energy(db, "tidal:near", energy=near)

    result = build_set(db, set_obj)

    assert result.slot_count == 1
    assert result.slots[0].track_id == "tidal:near"


# Track i is seeded with resolved energy == 2*i (a full 0..10 spread over 6
# tracks), so a slot's chosen energy is recoverable from its track_id suffix.
_CURVE_ENERGIES = [0, 2, 4, 6, 8, 10]


def _curve_mae(result) -> float:
    """Mean absolute error of each slot's chosen energy vs its target_energy."""
    errors = []
    for slot in result.slots:
        idx = (slot.track_id or "").split(":")[-1]
        if not idx.isdigit() or slot.target_energy is None:
            continue
        errors.append(abs(_CURVE_ENERGIES[int(idx)] - slot.target_energy))
    assert errors, "expected scored slots"
    return sum(errors) / len(errors)


def test_energy_curve_adherence_improves_with_resolved_energy(db: Session, test_user: User):
    """A/B on the SAME pool: building with resolved energy must track the target
    curve measurably better than the identical builder run energy-blind.

    The energy-blind baseline is reproduced by deleting the TrackVibe rows (pool
    rows are already ``None``), so the energy term collapses to its constant 0.5
    — exactly the pre-#543 behavior. Comparing the two MAEs isolates the fix from
    the refinement pass's transition-smoothing trade-offs, which are out of scope.
    """
    set_obj = _mk_set(db, test_user, duration=210 * 6)  # ~6 slots
    src = _mk_source(db, set_obj)

    for idx, energy in enumerate(_CURVE_ENERGIES):
        _mk_track(db, set_obj, src, idx, track_id=f"tidal:{idx}", bpm=124.0, key="8A", camelot="8A")
        _llm_energy(db, f"tidal:{idx}", energy=energy)

    aware_mae = _curve_mae(build_set(db, set_obj))

    # Energy-blind baseline: drop the LLM tier so nothing resolves; pool rows are
    # already None. Same pool, same curve, same builder.
    db.query(TrackVibe).delete()
    db.commit()
    blind_mae = _curve_mae(build_set(db, set_obj))

    assert aware_mae < blind_mae, (
        f"resolved energy did not improve curve adherence: aware={aware_mae} blind={blind_mae}"
    )


def test_missing_energy_degrades_neutrally(db: Session, test_user: User):
    """Tracks with no resolvable energy anywhere must not crash and must not be
    unfairly penalized: a full pool with zero vibe data still builds a set."""
    set_obj = _mk_set(db, test_user, duration=210 * 4)
    src = _mk_source(db, set_obj)
    for idx in range(6):
        _mk_track(db, set_obj, src, idx)  # energy None, no TrackVibe rows

    result = build_set(db, set_obj)

    assert result.slot_count >= 1
    assert all(s.track_id for s in result.slots)


def test_missing_owner_resolves_empty_vibes_no_crash(db: Session, test_user: User):
    """If the set's owner row is gone, vibe resolution degrades to an empty map
    (pre-#543 behavior) instead of crashing the build."""
    set_obj = _mk_set(db, test_user, duration=210 * 2)
    src = _mk_source(db, set_obj)
    for idx in range(3):
        _mk_track(db, set_obj, src, idx)
        _llm_energy(db, f"tidal:{idx}", energy=idx * 3)

    # Point the set at a non-existent owner so db.get(User, ...) returns None.
    set_obj.owner_id = 999_999
    db.commit()

    assert _pool_vibes(db, set_obj) == {}
    # The build still succeeds (energy term falls back to its neutral constant).
    result = build_set(db, set_obj)
    assert result.slot_count >= 1
    assert all(s.track_id for s in result.slots)


def test_resolved_mood_continuity_affects_transition_scores(db: Session, test_user: User):
    """Mood was dead the same way as energy. With resolved mood threaded in,
    same-mood neighbors should score a higher mood-continuity transition than a
    mood clash, which is observable in the persisted transition scores."""
    set_obj = _mk_set(db, test_user, duration=210 * 3)
    src = _mk_source(db, set_obj)
    # Three tracks; two share a mood, one differs. BPM/key identical so mood is
    # the differentiator.
    for idx in range(3):
        _mk_track(db, set_obj, src, idx, track_id=f"tidal:{idx}", bpm=124.0, key="8A", camelot="8A")
    _llm_energy(db, "tidal:0", energy=5, mood="dark")
    _llm_energy(db, "tidal:1", energy=5, mood="dark")
    _llm_energy(db, "tidal:2", energy=5, mood="happy")

    result = build_set(db, set_obj)

    # At least one adjacent same-mood pair should exist and its transition should
    # outscore the worst (mood-clash) transition.
    assert result.slot_count >= 2
    scores = [s.transition_score for s in result.slots[1:] if s.transition_score is not None]
    assert scores, "expected transition scores"
    # A purely energy/bpm/key-identical pool would have flat mood (0.5) everywhere;
    # with mood resolved, the same-mood transition rises above the clash one.
    assert max(scores) > min(scores)
