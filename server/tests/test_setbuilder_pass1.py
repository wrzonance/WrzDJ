"""Tests for WrzDJSet deterministic pass (#390)."""

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder.pass1_deterministic import build_set


def _mk_set(db: Session, user: User, *, duration: int | None = 14 * 60) -> Set:
    set_obj = Set(owner_id=user.id, name="Friday", target_duration_sec=duration)
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
    defaults = dict(
        set_id=set_obj.id,
        source_id=source.id,
        track_id=f"tidal:{idx}",
        title=f"Track {idx}",
        artist=f"Artist {idx}",
        bpm=124.0 + idx,
        key=f"{8 + (idx % 3)}A",
        camelot=f"{8 + (idx % 3)}A",
        energy=4 + idx,
        duration_sec=210,
        dedupe_sig=f"sig-{idx}",
    )
    defaults.update(kw)
    track = SetPoolTrack(**defaults)
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def test_build_set_fills_target_duration_deterministically(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, duration=14 * 60)
    src = _mk_source(db, set_obj)
    for idx in range(8):
        _mk_track(db, set_obj, src, idx)

    first = build_set(db, set_obj)
    first_ids = [s.track_id for s in first.slots]
    first_scores = [s.transition_score for s in first.slots]

    second = build_set(db, set_obj)

    # 14 min target, 210s tracks, overlap-aware (#538): the engine accumulates
    # real durations and stops once the overlap-discounted effective playtime
    # reaches the target — 5 slots (effective 816s at 4 < 840s <= 1018s at 5),
    # not the old overlap-blind round(840/210)=4.
    assert first.slot_count == 5
    assert [s.track_id for s in second.slots] == first_ids
    assert [s.transition_score for s in second.slots] == first_scores
    assert all(s.target_energy is not None for s in second.slots)
    assert first.iterations <= 50


def test_build_set_no_target_is_bounded_by_fallback_cap(db: Session, test_user: User):
    """No target must NOT dump the whole pool (#538 "12-hour set" bug). A 400-track
    pool with no target builds a set bounded by the 3-hour fallback cap, never 400."""
    set_obj = _mk_set(db, test_user, duration=None)
    src = _mk_source(db, set_obj)
    for idx in range(400):
        _mk_track(db, set_obj, src, idx, duration_sec=210)

    result = build_set(db, set_obj)

    # 3h fallback / ~210s overlap-aware ≈ 53 slots — bounded, never the 400 pool.
    assert result.slot_count < 400
    assert result.slot_count <= 60


def _build_durations(result, by_track_id: dict[str, int]) -> list[int]:
    return [by_track_id.get(s.track_id or "", 0) for s in result.slots]


def test_build_set_matches_overlap_aware_budget(db: Session, test_user: User):
    """Acceptance criterion (#538): the engine's slot count equals
    ``targeting.pass1_slot_budget_from_durations`` evaluated over the SAME real
    durations it accumulated — the engine is the load-bearing consumer of the
    targeting contract, not a parallel re-derivation. Variable lengths prove it
    isn't a uniform-bucket coincidence."""
    from app.services.setbuilder import targeting

    set_obj = _mk_set(db, test_user, duration=14 * 60)
    src = _mk_source(db, set_obj)
    durations: dict[str, int] = {}
    for idx in range(20):
        dur = 200 + idx
        track = _mk_track(db, set_obj, src, idx, duration_sec=dur)
        durations[track.track_id] = dur

    result = build_set(db, set_obj)
    budget = targeting.pass1_slot_budget_from_durations(
        target_duration_sec=14 * 60,
        track_durations_sec=_build_durations(result, durations),
        avg_transition_overlap_sec=set_obj.avg_transition_overlap_sec,
    )

    assert result.slot_count == budget.slot_count


def test_build_set_lands_within_overflow_tolerance(db: Session, test_user: User):
    """With granular track lengths the accumulated effective playtime lands within
    the overflow tolerance of the target — the overlap-aware budget is satisfied,
    not merely approached (#538)."""
    from app.services.setbuilder import targeting

    # 90s tracks, 30 min target: granular enough that stopping at the first slot
    # to cross the target stays within the 10% overflow band.
    set_obj = _mk_set(db, test_user, duration=30 * 60)
    src = _mk_source(db, set_obj)
    for idx in range(40):
        _mk_track(db, set_obj, src, idx, duration_sec=90)

    result = build_set(db, set_obj)
    budget = targeting.pass1_slot_budget_from_durations(
        target_duration_sec=30 * 60,
        track_durations_sec=[90] * result.slot_count,
        avg_transition_overlap_sec=set_obj.avg_transition_overlap_sec,
    )

    assert result.slot_count == budget.slot_count
    assert budget.within_overflow_tolerance is True


def test_build_set_preserves_locked_slots_and_tracks(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, duration=14 * 60)
    src = _mk_source(db, set_obj)
    locked_track = _mk_track(db, set_obj, src, 100, track_id="tidal:locked", title="Locked")
    for idx in range(8):
        _mk_track(db, set_obj, src, idx)
    db.add(SetSlot(set_id=set_obj.id, position=1, track_id=locked_track.track_id, locked=True))
    db.commit()

    result = build_set(db, set_obj)

    # Overlap-aware 14-min budget is 5 slots (#538); the locked slot at position 1
    # survives unchanged within the longer, length-gated set.
    assert result.slots[1].locked is True
    assert result.slots[1].track_id == "tidal:locked"
    assert [s.position for s in result.slots] == [0, 1, 2, 3, 4]
    assert len({s.track_id for s in result.slots if s.track_id}) == 5


def test_saved_pairing_boost_keeps_adjacent_pair(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, duration=7 * 60)
    src = _mk_source(db, set_obj)
    _mk_track(db, set_obj, src, 1, track_id="tidal:a", bpm=120, key="8A", energy=5)
    _mk_track(db, set_obj, src, 2, track_id="tidal:b", bpm=121, key="8A", energy=5)
    _mk_track(db, set_obj, src, 3, track_id="tidal:c", bpm=130, key="12B", energy=9)
    db.add_all(
        [
            SetSlot(set_id=set_obj.id, position=0, track_id="tidal:a"),
            SetSlot(set_id=set_obj.id, position=1, track_id="tidal:b"),
        ]
    )
    db.commit()

    result = build_set(db, set_obj)

    # The saved a->b pairing boost keeps them adjacent and in order. The
    # overlap-aware 7-min budget now admits a third slot (#538), so assert the
    # pairing invariant (a then b at the head) rather than an exact 2-slot length.
    ids = [slot.track_id for slot in result.slots]
    assert ids[:2] == ["tidal:a", "tidal:b"]


def test_build_set_commit_false_defers_persistence_to_caller(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, duration=7 * 60)
    src = _mk_source(db, set_obj)
    for idx in range(4):
        _mk_track(db, set_obj, src, idx)

    # commit=False only flushes, so a rollback discards the generated slots.
    build_set(db, set_obj, commit=False)
    assert db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).count() > 0
    db.rollback()
    assert db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).count() == 0

    # Default commit=True persists across a rollback.
    build_set(db, set_obj)
    db.rollback()
    assert db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).count() > 0
