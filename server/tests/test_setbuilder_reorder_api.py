"""Endpoint tests for hand-drag slot reorder (#437)."""

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User


def _make_set_with_slots(db: Session, owner: User, n: int, locked_idx: int | None = None) -> Set:
    set_obj = Set(owner_id=owner.id, name="Friday", target_duration_sec=14 * 60)
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
            SetSlot(set_id=set_obj.id, position=i, track_id=f"tidal:{i}", locked=(i == locked_idx))
        )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _ordered_ids(client, set_id: int, headers) -> list[int]:
    rows = client.get(f"/api/setbuilder/sets/{set_id}/slots", headers=headers).json()
    return [r["id"] for r in sorted(rows, key=lambda r: r["position"])]


def test_reorder_slots_persists_new_order(client, db: Session, test_user: User, auth_headers):
    set_obj = _make_set_with_slots(db, test_user, 3)
    ids = _ordered_ids(client, set_obj.id, auth_headers)
    new_order = [ids[2], ids[0], ids[1]]

    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": new_order},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert _ordered_ids(client, set_obj.id, auth_headers) == new_order
    scores = {s["position"]: s for s in resp.json()}
    assert scores[0]["score"] == 100.0
    assert sorted(scores) == [0, 1, 2]
    assert isinstance(scores[1]["score"], (int, float))


def test_reorder_rejects_non_permutation(client, db: Session, test_user: User, auth_headers):
    set_obj = _make_set_with_slots(db, test_user, 3)
    ids = _ordered_ids(client, set_obj.id, auth_headers)
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": ids[:2]},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_reorder_rejects_moving_locked_slot(client, db: Session, test_user: User, auth_headers):
    set_obj = _make_set_with_slots(db, test_user, 3, locked_idx=1)
    ids = _ordered_ids(client, set_obj.id, auth_headers)
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": [ids[1], ids[0], ids[2]]},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert _ordered_ids(client, set_obj.id, auth_headers) == ids


def test_reorder_other_djs_set_is_404(
    client, db: Session, admin_user: User, test_user: User, auth_headers
):
    set_obj = _make_set_with_slots(db, admin_user, 3)
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": [s.id for s in set_obj.slots]},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_reorder_requires_active_user(client, db: Session, test_user: User, pending_headers):
    set_obj = _make_set_with_slots(db, test_user, 3)
    resp = client.put(
        f"/api/setbuilder/sets/{set_obj.id}/slots/order",
        json={"slot_ids": [s.id for s in set_obj.slots]},
        headers=pending_headers,
    )
    assert resp.status_code in (401, 403)
