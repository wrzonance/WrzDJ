"""Model tests for SetCurveTemplate and SetSlot.target_energy (#389)."""

import json

from app.models.curve_template import SetCurveTemplate
from app.models.set import Set, SetSlot


def test_create_curve_template(db, test_user):
    points = [{"t": 0, "e": 4, "label": "Start"}, {"t": 1.0, "e": 6, "label": "End"}]
    tpl = SetCurveTemplate(user_id=test_user.id, name="My Curve", points_json=json.dumps(points))
    db.add(tpl)
    db.commit()
    db.refresh(tpl)

    assert tpl.id > 0
    assert tpl.name == "My Curve"
    assert json.loads(tpl.points_json) == points
    assert tpl.created_at is not None
    assert tpl.updated_at is not None


def test_slot_target_energy_defaults_to_none(db, test_user):
    set_obj = Set(owner_id=test_user.id, name="S")
    db.add(set_obj)
    db.commit()
    slot = SetSlot(set_id=set_obj.id, position=0)
    db.add(slot)
    db.commit()
    db.refresh(slot)

    assert slot.target_energy is None
    slot.target_energy = 7.5
    db.commit()
    db.refresh(slot)
    assert slot.target_energy == 7.5
