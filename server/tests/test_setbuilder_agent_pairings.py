"""Tests for Pass 2 transition-pairing tools."""

import json

import pytest
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.set import Set, SetSlot
from app.models.user import User
from app.services.setbuilder.agent.pass2_agent import (
    AgentToolError,
    _agent_tools,
    _tool_display_summary,
    apply_tool_call,
)
from tests.setbuilder_agent_test_helpers import (
    _mk_set_for_curve,
    _mk_set_with_tracks,
    _pool_track_by_track_id,
)

# suggest_pairings / add_pairing / remove_pairing (#442, Family 3)
# ---------------------------------------------------------------------------


def _mk_set_with_three_slots(db: Session, user: User) -> Set:
    """A set whose first three pool tracks (tidal:0/1/2) fill slots 0/1/2."""
    set_obj = _mk_set_with_tracks(db, user)
    db.add(SetSlot(set_id=set_obj.id, position=2, track_id="tidal:2"))
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _pairing_rows(db: Session, set_id: int):
    from app.models.set_pairing import SetPairing

    return db.query(SetPairing).filter(SetPairing.set_id == set_id).all()


def test_suggest_pairings_reports_transitions_and_pinned_flag(db: Session, test_user: User):
    from app.services.setbuilder import pairings

    set_obj = _mk_set_with_three_slots(db, test_user)
    pairings.upsert_pairing(
        db,
        set_obj,
        from_track_id="tidal:0",
        into_track_id="tidal:1",
        cue_in_sec=None,
        note=None,
        tags=[],
    )

    result, affected = apply_tool_call(db, set_obj, "suggest_pairings", {})

    assert affected == set()
    transitions = result["transitions"]
    assert [t["position"] for t in transitions] == [1, 2]
    first, second = transitions
    assert first["is_pinned"] is True
    assert first["pairing_id"] is not None
    assert second["is_pinned"] is False
    assert second["pairing_id"] is None
    assert result["pinned_count"] == 1


def test_suggest_pairings_includes_pool_track_ids(db: Session, test_user: User):
    set_obj = _mk_set_with_three_slots(db, test_user)

    result, _ = apply_tool_call(db, set_obj, "suggest_pairings", {})

    first = result["transitions"][0]
    t0 = _pool_track_by_track_id(set_obj, "tidal:0")
    t1 = _pool_track_by_track_id(set_obj, "tidal:1")
    assert first["from"]["pool_track_id"] == t0.id
    assert first["into"]["pool_track_id"] == t1.id
    assert first["from"]["title"] == t0.title


def test_suggest_pairings_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_three_slots(db, test_user)
    before_count = db.query(Request).count()

    apply_tool_call(db, set_obj, "suggest_pairings", {})

    assert db.query(Request).count() == before_count


def test_add_pairing_creates_pairing(db: Session, test_user: User):
    set_obj = _mk_set_with_three_slots(db, test_user)
    t0 = _pool_track_by_track_id(set_obj, "tidal:0")
    t2 = _pool_track_by_track_id(set_obj, "tidal:2")

    result, affected = apply_tool_call(
        db,
        set_obj,
        "add_pairing",
        {
            "from_pool_track_id": t0.id,
            "into_pool_track_id": t2.id,
            "note": "Killer drop",
            "tags": ["peak", "PEAK", " peak "],
            "rationale": "These two always land together.",
        },
    )

    assert affected == set()
    assert result["created"] is True
    assert result["from_track_id"] == "tidal:0"
    assert result["into_track_id"] == "tidal:2"
    rows = _pairing_rows(db, set_obj.id)
    assert len(rows) == 1
    assert (rows[0].from_track_id, rows[0].into_track_id) == ("tidal:0", "tidal:2")
    assert json.loads(rows[0].tags_json) == ["peak"]  # normalized + de-duped


def test_add_pairing_is_idempotent_update(db: Session, test_user: User):
    set_obj = _mk_set_with_three_slots(db, test_user)
    t0 = _pool_track_by_track_id(set_obj, "tidal:0")
    t1 = _pool_track_by_track_id(set_obj, "tidal:1")
    payload = {
        "from_pool_track_id": t0.id,
        "into_pool_track_id": t1.id,
        "rationale": "Pin this transition.",
    }

    first, _ = apply_tool_call(db, set_obj, "add_pairing", payload)
    second, _ = apply_tool_call(db, set_obj, "add_pairing", payload)

    assert first["created"] is True
    assert second["created"] is False
    assert len(_pairing_rows(db, set_obj.id)) == 1


def test_add_pairing_rejects_same_track(db: Session, test_user: User):
    set_obj = _mk_set_with_three_slots(db, test_user)
    t0 = _pool_track_by_track_id(set_obj, "tidal:0")

    with pytest.raises(AgentToolError, match="different"):
        apply_tool_call(
            db,
            set_obj,
            "add_pairing",
            {
                "from_pool_track_id": t0.id,
                "into_pool_track_id": t0.id,
                "rationale": "A track cannot pair with itself.",
            },
        )


def test_add_pairing_rejects_foreign_pool_track(db: Session, test_user: User):
    set_obj = _mk_set_with_three_slots(db, test_user)
    other = _mk_set_with_three_slots(db, test_user)
    home = _pool_track_by_track_id(set_obj, "tidal:0")
    foreign = _pool_track_by_track_id(other, "tidal:2")

    with pytest.raises(AgentToolError, match="Pool track not found"):
        apply_tool_call(
            db,
            set_obj,
            "add_pairing",
            {
                "from_pool_track_id": home.id,
                "into_pool_track_id": foreign.id,
                "rationale": "Cross-set pairing must be rejected.",
            },
        )


def test_add_pairing_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set_with_three_slots(db, test_user)
    t0 = _pool_track_by_track_id(set_obj, "tidal:0")
    t1 = _pool_track_by_track_id(set_obj, "tidal:1")

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(
            db,
            set_obj,
            "add_pairing",
            {"from_pool_track_id": t0.id, "into_pool_track_id": t1.id},
        )


def test_add_pairing_defers_commit(db: Session, test_user: User):
    """add_pairing flushes but does not commit, so the turn can still roll back."""
    set_obj = _mk_set_with_three_slots(db, test_user)
    t0 = _pool_track_by_track_id(set_obj, "tidal:0")
    t1 = _pool_track_by_track_id(set_obj, "tidal:1")

    apply_tool_call(
        db,
        set_obj,
        "add_pairing",
        {
            "from_pool_track_id": t0.id,
            "into_pool_track_id": t1.id,
            "rationale": "Tentative pin inside a turn.",
        },
    )
    db.rollback()

    assert _pairing_rows(db, set_obj.id) == []


def test_remove_pairing_deletes_pairing(db: Session, test_user: User):
    set_obj = _mk_set_with_three_slots(db, test_user)
    t0 = _pool_track_by_track_id(set_obj, "tidal:0")
    t1 = _pool_track_by_track_id(set_obj, "tidal:1")
    apply_tool_call(
        db,
        set_obj,
        "add_pairing",
        {"from_pool_track_id": t0.id, "into_pool_track_id": t1.id, "rationale": "pin"},
    )
    db.commit()

    result, affected = apply_tool_call(
        db,
        set_obj,
        "remove_pairing",
        {"from_pool_track_id": t0.id, "into_pool_track_id": t1.id, "rationale": "unpin"},
    )

    assert affected == set()
    assert result["removed"] is True
    assert _pairing_rows(db, set_obj.id) == []


def test_remove_pairing_missing_raises(db: Session, test_user: User):
    set_obj = _mk_set_with_three_slots(db, test_user)
    t0 = _pool_track_by_track_id(set_obj, "tidal:0")
    t1 = _pool_track_by_track_id(set_obj, "tidal:1")

    with pytest.raises(AgentToolError, match="No saved pairing"):
        apply_tool_call(
            db,
            set_obj,
            "remove_pairing",
            {"from_pool_track_id": t0.id, "into_pool_track_id": t1.id, "rationale": "x"},
        )


def test_add_pairing_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_three_slots(db, test_user)
    t0 = _pool_track_by_track_id(set_obj, "tidal:0")
    t1 = _pool_track_by_track_id(set_obj, "tidal:1")
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(
        db,
        set_obj,
        "add_pairing",
        {"from_pool_track_id": t0.id, "into_pool_track_id": t1.id, "rationale": "pin"},
    )

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_pairing_tools_registered():
    from app.services.setbuilder.agent.pass2_agent import MUTATION_TOOLS

    names = {tool.name for tool in _agent_tools()}
    assert {"suggest_pairings", "add_pairing", "remove_pairing"} <= names
    assert "suggest_pairings" not in MUTATION_TOOLS  # read-only
    assert {"add_pairing", "remove_pairing"} <= MUTATION_TOOLS


def test_tool_display_summary_pairings():
    added = _tool_display_summary(
        "add_pairing",
        {},
        {"created": True, "from_label": "A", "into_label": "B"},
        {},
        {},
    )
    assert added == "Pinned the transition A → B."

    updated = _tool_display_summary(
        "add_pairing",
        {},
        {"created": False, "from_label": "A", "into_label": "B"},
        {},
        {},
    )
    assert updated == "Updated the pinned transition A → B."

    removed = _tool_display_summary(
        "remove_pairing",
        {},
        {"removed": True, "from_label": "A", "into_label": "B"},
        {},
        {},
    )
    assert removed == "Unpinned the transition A → B."

    suggested = _tool_display_summary(
        "suggest_pairings",
        {},
        {"transitions": [{}, {}], "pinned_count": 1},
        {},
        {},
    )
    assert suggested == "Reviewed 2 transitions; 1 already pinned."


# CodeRabbit review fixes on PR #483 (regression pins)
# ---------------------------------------------------------------------------


def test_bump_energy_spec_allows_all_slots_mode():
    """slot_id is optional so the model can reach _tool_bump_energy's all-slots path."""
    spec = next(tool for tool in _agent_tools() if tool.name == "bump_energy")
    assert set(spec.input_schema["required"]) == {"amount", "rationale"}
    assert "slot_id" in spec.input_schema["properties"]


def test_apply_curve_template_rejects_both_builtin_and_template_id(db: Session, test_user: User):
    set_obj = _mk_set_for_curve(db, test_user, slot_count=3)
    with pytest.raises(AgentToolError, match="exactly one"):
        apply_tool_call(
            db,
            set_obj,
            "apply_curve_template",
            {"builtin": "peak", "template_id": 1, "rationale": "ambiguous template source"},
        )


def test_add_pairing_rejects_non_integer_pool_track_id(db: Session, test_user: User):
    set_obj = _mk_set_with_three_slots(db, test_user)
    with pytest.raises(AgentToolError, match="must be an integer"):
        apply_tool_call(
            db,
            set_obj,
            "add_pairing",
            {"from_pool_track_id": "abc", "into_pool_track_id": 1, "rationale": "bad id"},
        )
