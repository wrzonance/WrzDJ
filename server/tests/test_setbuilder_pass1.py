"""Tests for WrzDJSet deterministic pass (#390)."""

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder.pass1_deterministic import build_set


def _mk_set(db: Session, user: User, *, duration: int = 14 * 60) -> Set:
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

    assert first.slot_count == 4
    assert [s.track_id for s in second.slots] == first_ids
    assert [s.transition_score for s in second.slots] == first_scores
    assert all(s.target_energy is not None for s in second.slots)
    assert first.iterations <= 50


def test_build_set_preserves_locked_slots_and_tracks(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, duration=14 * 60)
    src = _mk_source(db, set_obj)
    locked_track = _mk_track(db, set_obj, src, 100, track_id="tidal:locked", title="Locked")
    for idx in range(8):
        _mk_track(db, set_obj, src, idx)
    db.add(SetSlot(set_id=set_obj.id, position=1, track_id=locked_track.track_id, locked=True))
    db.commit()

    result = build_set(db, set_obj)

    assert result.slots[1].locked is True
    assert result.slots[1].track_id == "tidal:locked"
    assert [s.position for s in result.slots] == [0, 1, 2, 3]
    assert len({s.track_id for s in result.slots if s.track_id}) == 4


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

    assert [slot.track_id for slot in result.slots] == ["tidal:a", "tidal:b"]
