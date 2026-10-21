"""Tests for Pass 2 contiguous slot-range movement."""

import pytest
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.set import SetSlot
from app.models.user import User
from app.services.setbuilder.agent.pass2_agent import (
    AgentToolError,
    _agent_tools,
    _tool_display_summary,
    apply_tool_call,
)
from tests.setbuilder_agent_test_helpers import _mk_set_for_curve

# move_range (#442, Family 3) — relocate a contiguous block of slots
# ---------------------------------------------------------------------------


def _ordered_track_ids(db: Session, set_id: int) -> list[str | None]:
    """Slot track_ids in position order — the visible timeline sequence."""
    rows = db.query(SetSlot).filter(SetSlot.set_id == set_id).order_by(SetSlot.position.asc()).all()
    return [row.track_id for row in rows]


def test_move_range_relocates_contiguous_block(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user, slot_count=5)

    result, affected = apply_tool_call(
        db,
        set_obj,
        "move_range",
        {
            "start_position": 1,
            "end_position": 2,
            "to_position": 3,
            "rationale": "Group the mid-set builders together before the peak.",
        },
    )

    # remaining = [0, 3, 4]; insert block [1, 2] at index 3 -> [0, 3, 4, 1, 2]
    assert _ordered_track_ids(db, set_obj.id) == [
        "tidal:0",
        "tidal:3",
        "tidal:4",
        "tidal:1",
        "tidal:2",
    ]
    assert result == {
        "start_position": 1,
        "end_position": 2,
        "to_position": 3,
        "moved_count": 2,
    }
    # Everything from the block's old start (1) to its new end (4) is touched.
    assert affected == {1, 2, 3, 4}


def test_move_range_to_front(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user, slot_count=5)

    apply_tool_call(
        db,
        set_obj,
        "move_range",
        {
            "start_position": 2,
            "end_position": 3,
            "to_position": 0,
            "rationale": "Open with the two anthems.",
        },
    )

    assert _ordered_track_ids(db, set_obj.id) == [
        "tidal:2",
        "tidal:3",
        "tidal:0",
        "tidal:1",
        "tidal:4",
    ]


def test_move_range_clamps_to_position_past_end(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user, slot_count=4)

    result, _ = apply_tool_call(
        db,
        set_obj,
        "move_range",
        {
            "start_position": 0,
            "end_position": 0,
            "to_position": 99,
            "rationale": "Send the opener to the very end.",
        },
    )

    assert _ordered_track_ids(db, set_obj.id) == [
        "tidal:1",
        "tidal:2",
        "tidal:3",
        "tidal:0",
    ]
    assert result["to_position"] == 3  # clamped to len(remaining)


def test_move_range_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user, slot_count=4)

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(
            db,
            set_obj,
            "move_range",
            {"start_position": 0, "end_position": 1, "to_position": 2},
        )


def test_move_range_rejects_invalid_span(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user, slot_count=4)

    with pytest.raises(AgentToolError, match="start_position"):
        apply_tool_call(
            db,
            set_obj,
            "move_range",
            {
                "start_position": 2,
                "end_position": 1,
                "to_position": 0,
                "rationale": "Inverted span should be rejected.",
            },
        )


def test_move_range_rejects_locked_slot_in_block(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user, slot_count=5)
    slots = sorted(set_obj.slots, key=lambda s: s.position)
    slots[2].locked = True
    db.commit()

    with pytest.raises(AgentToolError, match="locked"):
        apply_tool_call(
            db,
            set_obj,
            "move_range",
            {
                "start_position": 1,
                "end_position": 2,
                "to_position": 4,
                "rationale": "Tried to drag a pinned slot inside the block.",
            },
        )


def test_move_range_rejects_displacing_locked_slot(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user, slot_count=5)
    slots = sorted(set_obj.slots, key=lambda s: s.position)
    slots[0].locked = True  # pinned opener
    db.commit()

    with pytest.raises(AgentToolError, match="locked"):
        apply_tool_call(
            db,
            set_obj,
            "move_range",
            {
                "start_position": 3,
                "end_position": 4,
                "to_position": 0,
                "rationale": "Moving the closers to the front would shove the pinned opener.",
            },
        )


def test_move_range_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_for_curve(db, test_user, slot_count=4)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(
        db,
        set_obj,
        "move_range",
        {
            "start_position": 0,
            "end_position": 1,
            "to_position": 2,
            "rationale": "Reorder must never touch the request queue.",
        },
    )

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_move_range_registered_as_mutation_tool():
    from app.services.setbuilder.agent.pass2_agent import MUTATION_TOOLS

    assert "move_range" in MUTATION_TOOLS
    assert "move_range" in {tool.name for tool in _agent_tools()}


def test_tool_display_summary_move_range():
    summary = _tool_display_summary(
        "move_range",
        {},
        {"start_position": 1, "end_position": 2, "to_position": 3, "moved_count": 2},
        {},
        {},
    )
    assert summary == "Moved slots 2–3 to slot 4."

    single = _tool_display_summary(
        "move_range",
        {},
        {"start_position": 0, "end_position": 0, "to_position": 3, "moved_count": 1},
        {},
        {},
    )
    assert single == "Moved slot 1 to slot 4."


# suggest_pairings / add_pairing / remove_pairing (#442, Family 3)
