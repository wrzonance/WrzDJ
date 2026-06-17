"""Tests for DJ-driven full-order slot reordering (#437)."""

import pytest
from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder.reorder import ReorderError, apply_slot_order


def _set_with_slots(db: Session, user: User, n: int, locked_idx: int | None = None) -> Set:
    set_obj = Set(owner_id=user.id, name="Friday", target_duration_sec=14 * 60)
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)
    src = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(src)
    db.commit()
    db.refresh(src)
    for i in range(n):
        db.add(
            SetPoolTrack(
                set_id=set_obj.id,
                source_id=src.id,
                track_id=f"tidal:{i}",
                title=f"T{i}",
                artist=f"A{i}",
                bpm=120.0 + i,
                key="8A",
                camelot="8A",
                energy=5,
                duration_sec=210,
                dedupe_sig=f"sig-{i}",
            )
        )
        db.add(
            SetSlot(
                set_id=set_obj.id,
                position=i,
                track_id=f"tidal:{i}",
                locked=(i == locked_idx),
            )
        )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _ids_in_order(set_obj: Set) -> list[int]:
    return [s.id for s in sorted(set_obj.slots, key=lambda s: s.position)]


def test_apply_slot_order_reassigns_positions(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3)
    ids = _ids_in_order(set_obj)
    new_order = [ids[2], ids[0], ids[1]]

    apply_slot_order(db, set_obj, new_order)
    db.refresh(set_obj)

    assert _ids_in_order(set_obj) == new_order
    assert sorted(s.position for s in set_obj.slots) == [0, 1, 2]


def test_apply_slot_order_recomputes_transition_scores(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3)
    ids = _ids_in_order(set_obj)

    scores = apply_slot_order(db, set_obj, [ids[2], ids[0], ids[1]])

    by_pos = {s.position: s for s in scores}
    assert by_pos[0].score == 100.0
    assert {s.slot_id for s in scores} == set(ids)


def test_apply_slot_order_rejects_non_permutation(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3)
    ids = _ids_in_order(set_obj)
    with pytest.raises(ReorderError, match="permutation"):
        apply_slot_order(db, set_obj, [ids[0], ids[1]])
    with pytest.raises(ReorderError, match="permutation"):
        apply_slot_order(db, set_obj, [ids[0], ids[1], 99999])
    with pytest.raises(ReorderError, match="permutation"):
        apply_slot_order(db, set_obj, [ids[0], ids[0], ids[1]])


def test_apply_slot_order_rejects_moving_locked_slot(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3, locked_idx=1)
    ids = _ids_in_order(set_obj)
    with pytest.raises(ReorderError, match="locked"):
        apply_slot_order(db, set_obj, [ids[1], ids[0], ids[2]])


def test_apply_slot_order_allows_reorder_that_keeps_locked_position(db: Session, test_user: User):
    set_obj = _set_with_slots(db, test_user, 3, locked_idx=1)
    ids = _ids_in_order(set_obj)
    apply_slot_order(db, set_obj, [ids[2], ids[1], ids[0]])
    db.refresh(set_obj)
    assert _ids_in_order(set_obj) == [ids[2], ids[1], ids[0]]
