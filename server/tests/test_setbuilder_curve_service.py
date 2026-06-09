"""Service tests for services/setbuilder/curve.py (#389).

Covers piecewise-linear interpolation, built-in template sanity, template
CRUD owner scoping, apply-to-slots (uniform + explicit midpoints), and
vibe-window round-trips through paired SetCurvePoint rows.
"""

import pytest

from app.models.set import Set, SetCurvePoint, SetSlot
from app.services.setbuilder import curve


def _mk_set_with_slots(db, owner_id, n=4):
    set_obj = Set(owner_id=owner_id, name="S")
    db.add(set_obj)
    db.commit()
    for i in range(n):
        db.add(SetSlot(set_id=set_obj.id, position=i))
    db.commit()
    db.refresh(set_obj)
    return set_obj


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------


def test_interpolate_linear_midpoint():
    points = [{"t": 0.0, "e": 0.0}, {"t": 1.0, "e": 10.0}]
    assert curve.interpolate_energy(points, 0.5) == pytest.approx(5.0)
    assert curve.interpolate_energy(points, 0.25) == pytest.approx(2.5)


def test_interpolate_clamps_t():
    points = [{"t": 0.0, "e": 3.0}, {"t": 1.0, "e": 7.0}]
    assert curve.interpolate_energy(points, -0.5) == pytest.approx(3.0)
    assert curve.interpolate_energy(points, 1.5) == pytest.approx(7.0)


def test_interpolate_piecewise_multi_segment():
    points = [{"t": 0.0, "e": 2.0}, {"t": 0.5, "e": 8.0}, {"t": 1.0, "e": 4.0}]
    assert curve.interpolate_energy(points, 0.25) == pytest.approx(5.0)
    assert curve.interpolate_energy(points, 0.75) == pytest.approx(6.0)
    assert curve.interpolate_energy(points, 0.5) == pytest.approx(8.0)


def test_targets_at_midpoints_rounds_to_tenth():
    points = [{"t": 0.0, "e": 0.0}, {"t": 1.0, "e": 10.0}]
    targets = curve.targets_at_midpoints(points, [1 / 3])
    assert targets == [3.3]


def test_uniform_midpoints():
    assert curve.uniform_midpoints(4) == [0.125, 0.375, 0.625, 0.875]
    assert curve.uniform_midpoints(0) == []


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------


def test_builtin_templates_present_and_well_formed():
    assert set(curve.BUILTIN_TEMPLATES) == {"Open-Format", "Wedding", "Prom", "Club Peak"}
    for points in curve.BUILTIN_TEMPLATES.values():
        assert points[0]["t"] == 0
        assert points[-1]["t"] == 1.0
        assert all(0 <= p["e"] <= 10 for p in points)
        ts = [p["t"] for p in points]
        assert ts == sorted(ts)


def test_windows_from_points_pairs_flags():
    points = curve.BUILTIN_TEMPLATES["Wedding"]
    windows = curve.windows_from_points(points)
    assert len(windows) == 1
    assert windows[0]["t0"] == pytest.approx(0.7)
    assert windows[0]["t1"] == pytest.approx(0.78)


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------


def test_template_crud_owner_scoped(db, test_user, admin_user):
    points = [{"t": 0.0, "e": 3.0, "label": "Start"}, {"t": 1.0, "e": 6.0, "label": "End"}]
    tpl = curve.create_template(db, test_user.id, "Mine", points)
    assert tpl.id > 0

    assert [t.name for t in curve.list_templates(db, test_user.id)] == ["Mine"]
    assert curve.list_templates(db, admin_user.id) == []
    assert curve.get_owned_template(db, tpl.id, admin_user.id) is None

    curve.update_template(db, tpl, "Renamed", [{"t": 0.0, "e": 1.0}, {"t": 1.0, "e": 2.0}])
    db.refresh(tpl)
    assert tpl.name == "Renamed"
    assert curve.template_points(tpl) == [{"t": 0.0, "e": 1.0}, {"t": 1.0, "e": 2.0}]

    curve.delete_template(db, tpl)
    assert curve.list_templates(db, test_user.id) == []


# ---------------------------------------------------------------------------
# Apply to slots
# ---------------------------------------------------------------------------


def test_apply_points_to_slots_uniform(db, test_user):
    set_obj = _mk_set_with_slots(db, test_user.id, n=2)
    points = [{"t": 0.0, "e": 0.0}, {"t": 1.0, "e": 10.0}]
    result = curve.apply_points_to_slots(db, set_obj, points, None)
    assert [t for _, t in result] == [2.5, 7.5]
    slots = db.query(SetSlot).filter_by(set_id=set_obj.id).order_by(SetSlot.position).all()
    assert [s.target_energy for s in slots] == [2.5, 7.5]


def test_apply_points_to_slots_explicit_midpoints(db, test_user):
    set_obj = _mk_set_with_slots(db, test_user.id, n=2)
    points = [{"t": 0.0, "e": 0.0}, {"t": 1.0, "e": 10.0}]
    result = curve.apply_points_to_slots(db, set_obj, points, [0.1, 0.9])
    assert [t for _, t in result] == [1.0, 9.0]


def test_apply_points_midpoint_count_mismatch_raises(db, test_user):
    set_obj = _mk_set_with_slots(db, test_user.id, n=3)
    points = [{"t": 0.0, "e": 0.0}, {"t": 1.0, "e": 10.0}]
    with pytest.raises(ValueError):
        curve.apply_points_to_slots(db, set_obj, points, [0.5])


def test_apply_points_no_slots_returns_empty(db, test_user):
    set_obj = _mk_set_with_slots(db, test_user.id, n=0)
    points = [{"t": 0.0, "e": 0.0}, {"t": 1.0, "e": 10.0}]
    assert curve.apply_points_to_slots(db, set_obj, points, None) == []


# ---------------------------------------------------------------------------
# Vibe windows
# ---------------------------------------------------------------------------


def test_vibe_windows_round_trip(db, test_user):
    set_obj = _mk_set_with_slots(db, test_user.id, n=1)
    windows = [
        {"t0_sec": 100, "t1_sec": 300, "label": "First Dance"},
        {"t0_sec": 900, "t1_sec": 1200, "label": "Peak Build"},
    ]
    curve.replace_vibe_windows(db, set_obj, windows)
    stored = curve.get_vibe_windows(db, set_obj.id)
    assert stored == windows

    # Replace-all semantics: a second PUT overwrites the first.
    curve.replace_vibe_windows(db, set_obj, [{"t0_sec": 0, "t1_sec": 60, "label": "Cocktail Hour"}])
    stored = curve.get_vibe_windows(db, set_obj.id)
    assert stored == [{"t0_sec": 0, "t1_sec": 60, "label": "Cocktail Hour"}]

    # Window rows are paired start/end curve points.
    rows = db.query(SetCurvePoint).filter_by(set_id=set_obj.id).all()
    assert len(rows) == 2
    assert sum(1 for r in rows if r.is_slow_window_start) == 1
    assert sum(1 for r in rows if r.is_slow_window_end) == 1


def test_vibe_windows_overlapping_round_trip(db, test_user):
    """Overlapping windows must pair correctly (insertion-order pairing)."""
    set_obj = _mk_set_with_slots(db, test_user.id, n=1)
    windows = [
        {"t0_sec": 0, "t1_sec": 1000, "label": "Cocktail Hour"},
        {"t0_sec": 100, "t1_sec": 200, "label": "First Dance"},
    ]
    stored = curve.replace_vibe_windows(db, set_obj, windows)
    assert stored == windows
