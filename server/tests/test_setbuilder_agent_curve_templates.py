"""Tests for Pass 2 curve-template application tools."""

import pytest
from sqlalchemy.orm import Session

from app.models.curve_template import SetCurveTemplate
from app.models.request import Request
from app.models.user import User
from app.services.setbuilder import curve
from app.services.setbuilder.agent.pass2_agent import (
    AgentToolError,
    _tool_display_summary,
    apply_tool_call,
)
from tests.setbuilder_agent_test_helpers import _mk_set_for_curve


def _save_template(db: Session, user: User, points: list[dict]) -> SetCurveTemplate:
    return curve.create_template(db, user.id, "My Curve", points)


def test_apply_curve_template_applies_builtin(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user)

    result, positions = apply_tool_call(
        db,
        set_obj,
        "apply_curve_template",
        {"builtin": "Club Peak", "rationale": "Reshape into a club peak arc."},
    )

    slots = sorted(set_obj.slots, key=lambda s: s.position)
    targets = [s.target_energy for s in slots]
    # Club Peak rises to a peak then cools — not the flat 5.0 baseline.
    assert targets != [5.0, 5.0, 5.0, 5.0]
    assert positions == {0, 1, 2, 3}
    assert [row["slot_id"] for row in result["targets"]] == [s.id for s in slots]
    assert all(0.0 <= row["target_energy"] <= 10.0 for row in result["targets"])


def test_apply_curve_template_emits_windows_from_builtin(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user)

    result, _ = apply_tool_call(
        db,
        set_obj,
        "apply_curve_template",
        {"builtin": "Wedding", "rationale": "Wedding-night energy shape."},
    )

    # Wedding carries a paired slow_start/slow_end → exactly one window.
    assert result["windows"] == [{"t0": 0.7, "t1": 0.78}]


def test_apply_curve_template_applies_owned_template(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user)
    tpl = _save_template(
        db,
        test_user,
        [{"t": 0, "e": 2, "label": "Low"}, {"t": 1, "e": 9, "label": "High"}],
    )

    result, positions = apply_tool_call(
        db,
        set_obj,
        "apply_curve_template",
        {"template_id": tpl.id, "rationale": "Ramp from low to high."},
    )

    slots = sorted(set_obj.slots, key=lambda s: s.position)
    targets = [s.target_energy for s in slots]
    # A monotonic 2->9 ramp interpolated at uniform midpoints is strictly rising.
    assert targets == sorted(targets)
    assert targets[0] < targets[-1]
    assert positions == {0, 1, 2, 3}
    assert result["windows"] == []


def test_apply_curve_template_unknown_builtin_raises(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user)

    with pytest.raises(AgentToolError, match="Template not found"):
        apply_tool_call(
            db,
            set_obj,
            "apply_curve_template",
            {"builtin": "Does Not Exist", "rationale": "x"},
        )


def test_apply_curve_template_rejects_foreign_template(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user)
    other = User(username="other-dj", password_hash="x", is_active=True)
    db.add(other)
    db.commit()
    foreign = curve.create_template(db, other.id, "Theirs", [{"t": 0, "e": 5}])

    with pytest.raises(AgentToolError, match="Template not found"):
        apply_tool_call(
            db,
            set_obj,
            "apply_curve_template",
            {"template_id": foreign.id, "rationale": "Steal their curve."},
        )


def test_apply_curve_template_missing_template_id_raises(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user)

    with pytest.raises(AgentToolError, match="Template not found"):
        apply_tool_call(
            db,
            set_obj,
            "apply_curve_template",
            {"template_id": 999999, "rationale": "Nope."},
        )


def test_apply_curve_template_requires_input(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user)

    with pytest.raises(AgentToolError, match="builtin or template_id"):
        apply_tool_call(
            db,
            set_obj,
            "apply_curve_template",
            {"rationale": "No shape given."},
        )


def test_apply_curve_template_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user)

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(
            db,
            set_obj,
            "apply_curve_template",
            {"builtin": "Club Peak"},
        )


def test_apply_curve_template_skips_locked_slot_energy(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user)
    slots = sorted(set_obj.slots, key=lambda s: s.position)
    locked = slots[1]
    locked.locked = True
    locked.target_energy = 3.3
    db.commit()

    result, positions = apply_tool_call(
        db,
        set_obj,
        "apply_curve_template",
        {"builtin": "Club Peak", "rationale": "Reshape but respect the lock."},
    )

    db.refresh(locked)
    # The locked slot keeps its DJ-chosen energy; its position is not reported.
    assert locked.target_energy == 3.3
    assert locked.position not in positions
    reported = {row["slot_id"]: row["target_energy"] for row in result["targets"]}
    assert locked.id not in reported
    # Unlocked slots were still re-targeted.
    assert positions == {0, 2, 3}


def test_apply_curve_template_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_for_curve(db, test_user)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(
        db,
        set_obj,
        "apply_curve_template",
        {"builtin": "Open-Format", "rationale": "Standard open-format arc."},
    )

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_apply_curve_template_in_mutation_tools():
    from app.services.setbuilder.agent.pass2_agent import MUTATION_TOOLS

    assert "apply_curve_template" in MUTATION_TOOLS


def test_tool_display_summary_apply_curve_template():
    summary = _tool_display_summary(
        "apply_curve_template",
        {"builtin": "Club Peak"},
        {"targets": [{"slot_id": 1, "target_energy": 7.0}], "windows": []},
        {},
        {},
    )

    assert summary == "Applied curve template Club Peak to 1 slot."
