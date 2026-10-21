"""Tests for Pass 2 slot locking and target configuration tools."""

import pytest
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.user import User
from app.services.setbuilder.agent.pass2_agent import (
    AgentToolError,
    _tool_display_summary,
    apply_tool_call,
)
from tests.setbuilder_agent_test_helpers import _mk_set_with_tracks


def test_lock_slot_sets_locked_true(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slot = sorted(set_obj.slots, key=lambda s: s.position)[0]
    assert slot.locked is False

    result, positions = apply_tool_call(
        db, set_obj, "lock_slot", {"slot_id": slot.id, "rationale": "Pin the opener."}
    )

    db.refresh(slot)
    assert slot.locked is True
    assert result == {"slot_id": slot.id, "locked": True, "position": slot.position}
    assert positions == {slot.position}


def test_lock_slot_is_idempotent(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slot = sorted(set_obj.slots, key=lambda s: s.position)[0]
    slot.locked = True
    db.flush()

    result, _ = apply_tool_call(
        db, set_obj, "lock_slot", {"slot_id": slot.id, "rationale": "Keep it pinned."}
    )

    db.refresh(slot)
    assert slot.locked is True
    assert result["locked"] is True


def test_unlock_slot_sets_locked_false(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slot = sorted(set_obj.slots, key=lambda s: s.position)[0]
    slot.locked = True
    db.flush()

    result, positions = apply_tool_call(
        db, set_obj, "unlock_slot", {"slot_id": slot.id, "rationale": "Release the pin."}
    )

    db.refresh(slot)
    assert slot.locked is False
    assert result == {"slot_id": slot.id, "locked": False, "position": slot.position}
    assert positions == {slot.position}


def test_lock_slot_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slot = sorted(set_obj.slots, key=lambda s: s.position)[0]

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(db, set_obj, "lock_slot", {"slot_id": slot.id})


def test_unlock_slot_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slot = sorted(set_obj.slots, key=lambda s: s.position)[0]

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(db, set_obj, "unlock_slot", {"slot_id": slot.id})


def test_lock_slot_rejects_foreign_slot(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    other = _mk_set_with_tracks(db, test_user)
    foreign_slot = sorted(other.slots, key=lambda s: s.position)[0]

    with pytest.raises(AgentToolError, match="Slot not found"):
        apply_tool_call(
            db, set_obj, "lock_slot", {"slot_id": foreign_slot.id, "rationale": "Pin it."}
        )


@pytest.mark.parametrize("bad_payload", [{}, {"slot_id": None}, {"slot_id": "not-an-int"}])
def test_lock_slot_normalizes_invalid_slot_id(db: Session, test_user: User, bad_payload):
    """Malformed slot_id from the model must surface as AgentToolError, not a raw
    KeyError/TypeError/ValueError that escapes the apply_tool_call contract."""
    set_obj = _mk_set_with_tracks(db, test_user)

    with pytest.raises(AgentToolError, match="slot_id must be an integer"):
        apply_tool_call(db, set_obj, "lock_slot", {**bad_payload, "rationale": "Pin it."})


def test_lock_slot_then_reorder_refuses_that_slot(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slot = sorted(set_obj.slots, key=lambda s: s.position)[0]
    apply_tool_call(db, set_obj, "lock_slot", {"slot_id": slot.id, "rationale": "Pin the opener."})

    with pytest.raises(AgentToolError, match="Locked"):
        apply_tool_call(
            db,
            set_obj,
            "reorder_slot",
            {"slot_id": slot.id, "position": 1, "rationale": "Try to move it."},
        )


def test_lock_slot_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_tracks(db, test_user)
    slot = sorted(set_obj.slots, key=lambda s: s.position)[0]
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(db, set_obj, "lock_slot", {"slot_id": slot.id, "rationale": "Pin the opener."})

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_tool_display_summary_lock_and_unlock():
    locked = _tool_display_summary(
        "lock_slot", {}, {"slot_id": 1, "locked": True}, {1: {"position": 0}}, {1: {"position": 0}}
    )
    unlocked = _tool_display_summary(
        "unlock_slot",
        {},
        {"slot_id": 1, "locked": False},
        {1: {"position": 2}},
        {1: {"position": 2}},
    )

    assert locked == "Locked slot 1."
    assert unlocked == "Unlocked slot 3."


def test_set_target_sets_every_field(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    result, positions = apply_tool_call(
        db,
        set_obj,
        "set_target",
        {
            "target_duration_sec": 3600,
            "bpm_floor": 120,
            "bpm_ceiling": 130,
            "key_strictness": 0.8,
            "avg_transition_overlap_sec": 12,
            "rationale": "Dial in a one-hour peak-time set.",
        },
    )

    assert positions == set()
    db.refresh(set_obj)
    assert set_obj.target_duration_sec == 3600
    assert set_obj.bpm_floor == 120
    assert set_obj.bpm_ceiling == 130
    assert set_obj.key_strictness == 0.8
    assert set_obj.avg_transition_overlap_sec == 12
    assert result == {
        "target_duration_sec": 3600,
        "bpm_floor": 120,
        "bpm_ceiling": 130,
        "key_strictness": 0.8,
        "avg_transition_overlap_sec": 12,
    }


def test_set_target_partial_update_leaves_others_unchanged(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    set_obj.bpm_floor = 118
    set_obj.bpm_ceiling = 128
    set_obj.key_strictness = 0.3
    db.commit()
    original_overlap = set_obj.avg_transition_overlap_sec

    result, _ = apply_tool_call(
        db,
        set_obj,
        "set_target",
        {"target_duration_sec": 5400, "rationale": "Stretch to 90 minutes."},
    )

    db.refresh(set_obj)
    assert set_obj.target_duration_sec == 5400
    # Omitted fields are untouched.
    assert set_obj.bpm_floor == 118
    assert set_obj.bpm_ceiling == 128
    assert set_obj.key_strictness == 0.3
    assert set_obj.avg_transition_overlap_sec == original_overlap
    # The result echoes only the fields the call actually set.
    assert result == {"target_duration_sec": 5400}


def test_set_target_clears_nullable_field_with_explicit_none(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)  # seeded target_duration_sec=420
    assert set_obj.target_duration_sec is not None

    result, _ = apply_tool_call(
        db,
        set_obj,
        "set_target",
        {"target_duration_sec": None, "rationale": "Drop the hard duration target."},
    )

    db.refresh(set_obj)
    assert set_obj.target_duration_sec is None
    assert result == {"target_duration_sec": None}


def test_set_target_rejects_inverted_bpm_window(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    with pytest.raises(AgentToolError, match="bpm_floor"):
        apply_tool_call(
            db,
            set_obj,
            "set_target",
            {"bpm_floor": 130, "bpm_ceiling": 120, "rationale": "oops"},
        )


def test_set_target_rejects_out_of_range_key_strictness(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    for bad in (-0.1, 1.5):
        with pytest.raises(AgentToolError, match="key_strictness"):
            apply_tool_call(
                db,
                set_obj,
                "set_target",
                {"key_strictness": bad, "rationale": "oops"},
            )


def test_set_target_rejects_negative_durations(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    with pytest.raises(AgentToolError, match="target_duration_sec"):
        apply_tool_call(
            db,
            set_obj,
            "set_target",
            {"target_duration_sec": -1, "rationale": "oops"},
        )
    with pytest.raises(AgentToolError, match="avg_transition_overlap_sec"):
        apply_tool_call(
            db,
            set_obj,
            "set_target",
            {"avg_transition_overlap_sec": -5, "rationale": "oops"},
        )


def test_set_target_rejects_inverted_bpm_against_existing_floor(db: Session, test_user: User):
    """A new ceiling below the already-stored floor must be rejected too."""
    set_obj = _mk_set_with_tracks(db, test_user)
    set_obj.bpm_floor = 125
    db.commit()

    with pytest.raises(AgentToolError, match="bpm_floor"):
        apply_tool_call(
            db,
            set_obj,
            "set_target",
            {"bpm_ceiling": 120, "rationale": "Lower the top end."},
        )


def test_set_target_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(db, set_obj, "set_target", {"target_duration_sec": 3600})


def test_set_target_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_tracks(db, test_user)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(
        db,
        set_obj,
        "set_target",
        {
            "target_duration_sec": 3000,
            "bpm_floor": 122,
            "bpm_ceiling": 128,
            "rationale": "Set the targets without touching anyone's requests.",
        },
    )

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_set_target_display_summary_is_human_readable():
    summary = _tool_display_summary(
        "set_target",
        {"rationale": "x"},
        {
            "target_duration_sec": 3600,
            "bpm_floor": 120,
            "bpm_ceiling": 130,
            "key_strictness": 0.8,
            "avg_transition_overlap_sec": 12,
        },
        {},
        {},
    )
    assert "duration 60 min" in summary
    assert "BPM 120-130" in summary
    assert "key strictness 0.8" in summary
    assert "transition overlap 12s" in summary


def test_set_target_display_summary_handles_clears_and_single_bounds():
    # Cleared nullable fields and a lone floor/ceiling render distinct phrasing.
    cleared = _tool_display_summary(
        "set_target",
        {"rationale": "x"},
        {"target_duration_sec": None, "bpm_floor": None},
        {},
        {},
    )
    assert "cleared duration target" in cleared
    assert "cleared BPM floor" in cleared

    floor_only = _tool_display_summary("set_target", {"rationale": "x"}, {"bpm_floor": 124}, {}, {})
    assert floor_only == "Set targets: BPM floor 124."

    ceiling_only = _tool_display_summary(
        "set_target", {"rationale": "x"}, {"bpm_ceiling": None}, {}, {}
    )
    assert ceiling_only == "Set targets: cleared BPM ceiling."

    # An empty result (no fields set) still yields a sentence, never a crash.
    assert _tool_display_summary("set_target", {"rationale": "x"}, {}, {}, {}) == (
        "Updated set targets."
    )


# --- apply_curve_template (#466) -------------------------------------------
