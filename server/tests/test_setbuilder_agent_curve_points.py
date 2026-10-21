"""Tests for Pass 2 standalone curve-point tools."""

import pytest
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.set import SetCurvePoint
from app.models.user import User
from app.services.setbuilder import curve
from app.services.setbuilder.agent.pass2_agent import (
    AgentToolError,
    _agent_tools,
    _tool_display_summary,
    apply_tool_call,
)
from tests.setbuilder_agent_test_helpers import _mk_set_with_tracks

# set_curve_point / remove_curve_point (#468)
# ---------------------------------------------------------------------------


def _standalone_points(db: Session, set_id: int) -> list[SetCurvePoint]:
    """Non-window curve points for a set, ordered by time offset."""
    return (
        db.query(SetCurvePoint)
        .filter(
            SetCurvePoint.set_id == set_id,
            SetCurvePoint.is_slow_window_start == False,  # noqa: E712
            SetCurvePoint.is_slow_window_end == False,  # noqa: E712
        )
        .order_by(SetCurvePoint.position_sec.asc())
        .all()
    )


def test_set_curve_point_inserts_non_window_point(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    result, affected = apply_tool_call(
        db,
        set_obj,
        "set_curve_point",
        {"position_sec": 120, "energy": 7, "label": "Lift", "rationale": "build the room"},
    )
    db.commit()

    assert affected == set()
    assert result["position_sec"] == 120
    assert result["energy"] == 7
    assert result["label"] == "Lift"
    points = _standalone_points(db, set_obj.id)
    assert len(points) == 1
    assert points[0].is_slow_window_start is False
    assert points[0].is_slow_window_end is False


def test_set_curve_point_upserts_at_same_position(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    apply_tool_call(
        db,
        set_obj,
        "set_curve_point",
        {"position_sec": 90, "energy": 4, "label": "Warm", "rationale": "warm-up"},
    )
    db.commit()

    result, _ = apply_tool_call(
        db,
        set_obj,
        "set_curve_point",
        {"position_sec": 90, "energy": 9, "label": "Peak", "rationale": "raise it"},
    )
    db.commit()

    points = _standalone_points(db, set_obj.id)
    assert len(points) == 1  # updated, not duplicated
    assert points[0].energy == 9
    assert points[0].label == "Peak"
    assert result["point_id"] == points[0].id


def test_remove_curve_point_removes_non_window_point(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    apply_tool_call(
        db,
        set_obj,
        "set_curve_point",
        {"position_sec": 150, "energy": 6, "rationale": "marker"},
    )
    db.commit()

    result, affected = apply_tool_call(
        db,
        set_obj,
        "remove_curve_point",
        {"position_sec": 150, "rationale": "no longer needed"},
    )
    db.commit()

    assert affected == set()
    assert result["removed_position_sec"] == 150
    assert _standalone_points(db, set_obj.id) == []


def test_curve_point_tools_never_touch_slow_window_rows(db: Session, test_user: User):
    """Upsert + remove must leave paired vibe-window rows completely intact."""
    set_obj = _mk_set_with_tracks(db, test_user)
    curve.replace_vibe_windows(
        db,
        set_obj,
        [{"t0_sec": 100, "t1_sec": 200, "label": "Slow set"}],
        commit=True,
    )
    window_before = curve.get_vibe_windows(db, set_obj.id)
    assert window_before == [{"t0_sec": 100, "t1_sec": 200, "label": "Slow set"}]

    # A standalone point sharing a window boundary's position_sec must NOT
    # match the window row — it inserts a distinct non-window row.
    apply_tool_call(
        db,
        set_obj,
        "set_curve_point",
        {"position_sec": 100, "energy": 8, "rationale": "overlap boundary"},
    )
    db.commit()
    apply_tool_call(
        db,
        set_obj,
        "remove_curve_point",
        {"position_sec": 100, "rationale": "remove standalone"},
    )
    db.commit()

    # Windows survive both operations untouched.
    assert curve.get_vibe_windows(db, set_obj.id) == window_before
    window_rows = (
        db.query(SetCurvePoint)
        .filter(
            SetCurvePoint.set_id == set_obj.id,
            (SetCurvePoint.is_slow_window_start == True)  # noqa: E712
            | (SetCurvePoint.is_slow_window_end == True),  # noqa: E712
        )
        .count()
    )
    assert window_rows == 2


def test_remove_curve_point_does_not_remove_window_row(db: Session, test_user: User):
    """remove_curve_point keyed at a window boundary errors, leaving the pair."""
    set_obj = _mk_set_with_tracks(db, test_user)
    curve.replace_vibe_windows(
        db, set_obj, [{"t0_sec": 100, "t1_sec": 200, "label": "Slow"}], commit=True
    )

    with pytest.raises(AgentToolError, match="No curve point"):
        apply_tool_call(
            db,
            set_obj,
            "remove_curve_point",
            {"position_sec": 100, "rationale": "try to nuke window"},
        )

    assert curve.get_vibe_windows(db, set_obj.id) == [
        {"t0_sec": 100, "t1_sec": 200, "label": "Slow"}
    ]


def test_set_curve_point_rejects_out_of_range_energy(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    for bad in (-1, 11):
        with pytest.raises(AgentToolError, match="energy must be between 0 and 10"):
            apply_tool_call(
                db,
                set_obj,
                "set_curve_point",
                {"position_sec": 60, "energy": bad, "rationale": "bad energy"},
            )


def test_curve_point_tools_require_rationale(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    with pytest.raises(AgentToolError, match="requires a rationale"):
        apply_tool_call(db, set_obj, "set_curve_point", {"position_sec": 60, "energy": 5})
    with pytest.raises(AgentToolError, match="requires a rationale"):
        apply_tool_call(db, set_obj, "remove_curve_point", {"position_sec": 60})


def test_remove_curve_point_missing_raises(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    with pytest.raises(AgentToolError, match="No curve point"):
        apply_tool_call(
            db,
            set_obj,
            "remove_curve_point",
            {"position_sec": 999, "rationale": "nothing here"},
        )


def test_curve_point_tools_leave_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_tracks(db, test_user)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(
        db,
        set_obj,
        "set_curve_point",
        {"position_sec": 80, "energy": 6, "rationale": "marker"},
    )
    apply_tool_call(
        db,
        set_obj,
        "remove_curve_point",
        {"position_sec": 80, "rationale": "cleanup"},
    )
    db.commit()

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_set_curve_point_display_summary_is_human_readable():
    summary = _tool_display_summary(
        "set_curve_point",
        {},
        {"point_id": 1, "position_sec": 120, "energy": 7, "label": "Lift"},
        {},
        {},
    )
    assert "120s" in summary
    assert "energy 7" in summary
    assert "Lift" in summary


def test_remove_curve_point_display_summary_is_human_readable():
    summary = _tool_display_summary(
        "remove_curve_point",
        {},
        {"removed_position_sec": 120},
        {},
        {},
    )
    assert summary == "Removed curve point at 120s."


def test_set_curve_point_schema_keeps_label_optional():
    """label is optional; position_sec/energy/rationale stay required."""
    spec = next(t for t in _agent_tools() if t.name == "set_curve_point")
    required = set(spec.input_schema["required"])
    assert required == {"position_sec", "energy", "rationale"}
    assert "label" not in required
    assert "label" in spec.input_schema["properties"]
