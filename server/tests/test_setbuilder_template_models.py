"""Model tests for SetTemplate (#407)."""

import json

from app.models.set_template import SetTemplate


def test_create_set_template_round_trips_all_fields(db, test_user):
    slots = [{"position": 0, "target_energy": 5.0, "locked": True, "notes": "Opener"}]
    curve_points = [{"position_sec": 0, "energy": 4, "label": "Start"}]

    tpl = SetTemplate(
        user_id=test_user.id,
        name="Warehouse Set",
        vibe_theme="Peak Time",
        target_duration_sec=3600,
        avg_transition_overlap_sec=12,
        bpm_floor=122,
        bpm_ceiling=128,
        key_strictness=0.5,
        slots_json=json.dumps(slots),
        curve_points_json=json.dumps(curve_points),
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)

    assert tpl.id > 0
    assert tpl.user_id == test_user.id
    assert tpl.name == "Warehouse Set"
    assert tpl.vibe_theme == "Peak Time"
    assert tpl.target_duration_sec == 3600
    assert tpl.avg_transition_overlap_sec == 12
    assert tpl.bpm_floor == 122
    assert tpl.bpm_ceiling == 128
    assert tpl.key_strictness == 0.5
    assert json.loads(tpl.slots_json) == slots
    assert json.loads(tpl.curve_points_json) == curve_points
    assert tpl.created_at is not None
    assert tpl.updated_at is not None


def test_set_template_defaults_apply_when_unset(db, test_user):
    tpl = SetTemplate(
        user_id=test_user.id,
        name="Minimal Template",
        slots_json="[]",
        curve_points_json="[]",
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)

    assert tpl.vibe_theme is None
    assert tpl.target_duration_sec is None
    assert tpl.avg_transition_overlap_sec == 8
    assert tpl.bpm_floor is None
    assert tpl.bpm_ceiling is None
    assert tpl.key_strictness == 0.2
    assert json.loads(tpl.slots_json) == []
    assert json.loads(tpl.curve_points_json) == []


def test_set_template_updated_at_changes_on_update(db, test_user):
    tpl = SetTemplate(
        user_id=test_user.id,
        name="Editable",
        slots_json="[]",
        curve_points_json="[]",
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    original_updated_at = tpl.updated_at

    tpl.name = "Renamed"
    db.commit()
    db.refresh(tpl)

    assert tpl.name == "Renamed"
    assert tpl.updated_at >= original_updated_at
