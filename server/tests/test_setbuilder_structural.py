"""Tests for the destructive structural WrzDJSet agent tools (#491, #442 Family 3)."""

import pytest
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.llm.base import ChatResponse, ToolCall
from app.services.setbuilder.agent_display import _tool_display_summary
from app.services.setbuilder.document_snapshot import build_snapshot, restore_snapshot
from app.services.setbuilder.pass2_agent import (
    MUTATION_TOOLS,
    AgentToolError,
    apply_tool_call,
    chat_with_agent,
)


def _mk_set(db: Session, user: User, *, n_tracks: int, n_slots: int, duration: int) -> Set:
    """Set with ``n_tracks`` pool tracks (210s each) and ``n_slots`` seeded slots."""
    set_obj = Set(owner_id=user.id, name="Structural Set", target_duration_sec=duration)
    db.add(set_obj)
    db.flush()
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.flush()
    db.add_all(
        [
            SetPoolTrack(
                set_id=set_obj.id,
                source_id=source.id,
                track_id=f"tidal:{idx}",
                title=f"Track {idx}",
                artist=f"Artist {idx}",
                bpm=124 + idx,
                key="8A",
                camelot="8A",
                energy=5,
                duration_sec=210,
                dedupe_sig=f"struct-sig-{idx}",
            )
            for idx in range(n_tracks)
        ]
    )
    db.flush()
    db.add_all(
        [SetSlot(set_id=set_obj.id, position=i, track_id=f"tidal:{i}") for i in range(n_slots)]
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def test_autobuild_regenerates_order_and_reports_counts(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=4, n_slots=0, duration=14 * 60)

    result, positions = apply_tool_call(
        db, set_obj, "autobuild", {"rationale": "Auto-arrange from the pool."}
    )

    slots = db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).all()
    assert result["slot_count"] == len(slots)
    assert result["slot_count"] > 0
    assert isinstance(result["iterations"], int)
    assert positions == {s.position for s in slots}


def test_autobuild_preserves_locked_slot(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=6, n_slots=0, duration=14 * 60)
    db.add(SetSlot(set_id=set_obj.id, position=1, track_id="tidal:5", locked=True))
    db.commit()

    apply_tool_call(db, set_obj, "autobuild", {"rationale": "Rebuild around the pin."})

    locked = (
        db.query(SetSlot)
        .filter(SetSlot.set_id == set_obj.id, SetSlot.locked == True)  # noqa: E712
        .one()
    )
    assert locked.position == 1
    assert locked.track_id == "tidal:5"


def test_autobuild_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=0, duration=7 * 60)

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(db, set_obj, "autobuild", {})


def test_autobuild_in_mutation_tools():
    assert "autobuild" in MUTATION_TOOLS


def test_autobuild_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set(db, test_user, n_tracks=4, n_slots=0, duration=14 * 60)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(db, set_obj, "autobuild", {"rationale": "Rebuild it."})

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


@pytest.mark.asyncio
async def test_autobuild_then_failing_tool_rolls_back_whole_turn(
    monkeypatch, db: Session, test_user: User
):
    """commit=False means a later tool failure rolls the autobuild back too."""
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=2, duration=7 * 60)
    original = [
        s.track_id
        for s in db.query(SetSlot)
        .filter(SetSlot.set_id == set_obj.id)
        .order_by(SetSlot.position)
        .all()
    ]

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(id="ab", name="autobuild", input={"rationale": "Rebuild."}),
                ToolCall(
                    id="boom",
                    name="swap_slots",
                    input={"slot_a_id": 999999, "slot_b_id": 999998, "rationale": "boom"},
                ),
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    with pytest.raises(AgentToolError):
        await chat_with_agent(db, test_user, set_obj, message="Rebuild then break")

    remaining = [
        s.track_id
        for s in db.query(SetSlot)
        .filter(SetSlot.set_id == set_obj.id)
        .order_by(SetSlot.position)
        .all()
    ]
    assert remaining == original


def test_autobuild_then_restore_snapshot_returns_prior_order(db: Session, test_user: User):
    """#491 acceptance: the captured snapshot restores the exact pre-autobuild order."""
    set_obj = _mk_set(db, test_user, n_tracks=4, n_slots=2, duration=14 * 60)
    before = build_snapshot(set_obj)
    before_ids = [s.track_id for s in sorted(set_obj.slots, key=lambda s: s.position)]

    apply_tool_call(db, set_obj, "autobuild", {"rationale": "Rebuild wholesale."})
    db.commit()
    db.refresh(set_obj)

    restore_snapshot(db, set_obj, before)
    db.refresh(set_obj)

    after_ids = [s.track_id for s in sorted(set_obj.slots, key=lambda s: s.position)]
    assert after_ids == before_ids


def test_autobuild_display_summary_is_human_readable():
    summary = _tool_display_summary(
        "autobuild", {"rationale": "x"}, {"slot_count": 12, "iterations": 3}, {}, {}
    )
    assert summary == "Rebuilt the set: 12 slots, 3 refinement passes."

    one = _tool_display_summary(
        "autobuild", {"rationale": "x"}, {"slot_count": 1, "iterations": 1}, {}, {}
    )
    assert one == "Rebuilt the set: 1 slot, 1 refinement pass."


def test_fill_to_duration_stops_at_target(db: Session, test_user: User):
    # 1 seeded slot (210s) + 4 unused tracks; target 840s needs 3 more (4*210=840).
    set_obj = _mk_set(db, test_user, n_tracks=5, n_slots=1, duration=4 * 210)

    result, positions = apply_tool_call(
        db, set_obj, "fill_to_duration", {"rationale": "Fill to the target."}
    )

    assert result["inserted_count"] == 3
    assert result["estimated_total_sec"] == 4 * 210
    assert result["capped"] is False
    assert result["pool_exhausted"] is False
    assert db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).count() == 4
    assert positions == {1, 2, 3}


def test_fill_to_duration_stops_when_pool_exhausted(db: Session, test_user: User):
    # Only 2 unused tracks but the target wants far more — stop, flag exhausted.
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=1, duration=99 * 210)

    result, _ = apply_tool_call(
        db, set_obj, "fill_to_duration", {"rationale": "Use everything available."}
    )

    assert result["inserted_count"] == 2
    assert result["pool_exhausted"] is True
    assert result["capped"] is False


def test_fill_to_duration_respects_insert_cap(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=6, n_slots=1, duration=99 * 210)
    monkeypatch.setattr("app.services.setbuilder.agent_tools_structural.MAX_FILL_INSERTS", 2)

    result, _ = apply_tool_call(db, set_obj, "fill_to_duration", {"rationale": "Bounded fill."})

    assert result["inserted_count"] == 2
    assert result["capped"] is True


def test_fill_to_duration_errors_without_target(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=1, duration=7 * 60)
    set_obj.target_duration_sec = None
    db.commit()

    with pytest.raises(AgentToolError, match="target duration"):
        apply_tool_call(db, set_obj, "fill_to_duration", {"rationale": "Fill it."})


def test_fill_to_duration_zero_target_is_noop(db: Session, test_user: User):
    # A target of 0 is a valid assigned value (set_target allows min 0), not
    # "missing": fill treats it as already met and appends nothing instead of
    # raising. Regression for the `if not target` → `if target is None` fix.
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=1, duration=7 * 60)
    set_obj.target_duration_sec = 0
    db.commit()

    result, positions = apply_tool_call(
        db, set_obj, "fill_to_duration", {"rationale": "Target is zero."}
    )

    assert result["inserted_count"] == 0
    assert result["capped"] is False
    assert result["pool_exhausted"] is False
    assert positions == set()
    assert db.query(SetSlot).filter(SetSlot.set_id == set_obj.id).count() == 1


def test_fill_to_duration_never_moves_locked_slot(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=5, n_slots=0, duration=4 * 210)
    db.add(SetSlot(set_id=set_obj.id, position=0, track_id="tidal:0", locked=True))
    db.commit()

    apply_tool_call(db, set_obj, "fill_to_duration", {"rationale": "Append after the pin."})

    locked = (
        db.query(SetSlot)
        .filter(SetSlot.set_id == set_obj.id, SetSlot.locked == True)  # noqa: E712
        .one()
    )
    assert locked.position == 0
    assert locked.track_id == "tidal:0"


def test_fill_to_duration_requires_rationale(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user, n_tracks=3, n_slots=1, duration=7 * 60)

    with pytest.raises(AgentToolError, match="rationale"):
        apply_tool_call(db, set_obj, "fill_to_duration", {})


def test_fill_to_duration_in_mutation_tools():
    assert "fill_to_duration" in MUTATION_TOOLS


def test_fill_to_duration_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set(db, test_user, n_tracks=5, n_slots=1, duration=4 * 210)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(db, set_obj, "fill_to_duration", {"rationale": "Fill to target."})

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_fill_to_duration_display_summary_is_human_readable():
    added = _tool_display_summary(
        "fill_to_duration",
        {"rationale": "x"},
        {
            "inserted_count": 3,
            "estimated_total_sec": 840,
            "target_duration_sec": 840,
            "capped": False,
            "pool_exhausted": False,
        },
        {},
        {},
    )
    assert added == "Added 3 tracks toward target; now ~14 min of ~14 min."

    none_added = _tool_display_summary(
        "fill_to_duration",
        {"rationale": "x"},
        {
            "inserted_count": 0,
            "estimated_total_sec": 600,
            "target_duration_sec": 600,
            "capped": False,
            "pool_exhausted": False,
        },
        {},
        {},
    )
    assert none_added == "No tracks added; set already ~10 min of ~10 min target."


def test_duration_for_falls_back_to_average_when_missing():
    from app.services.setbuilder.agent_tools_structural import (
        AVG_TRACK_LENGTH_SEC,
        _duration_for,
    )

    class _FakeTrack:
        duration_sec = None

    assert _duration_for(None) == AVG_TRACK_LENGTH_SEC
    assert _duration_for(_FakeTrack()) == AVG_TRACK_LENGTH_SEC
    _FakeTrack.duration_sec = 0
    assert _duration_for(_FakeTrack()) == AVG_TRACK_LENGTH_SEC
    _FakeTrack.duration_sec = 180
    assert _duration_for(_FakeTrack()) == 180


def test_fill_to_duration_display_summary_notes_cap():
    capped = _tool_display_summary(
        "fill_to_duration",
        {"rationale": "x"},
        {
            "inserted_count": 2,
            "estimated_total_sec": 420,
            "target_duration_sec": 9999,
            "capped": True,
            "pool_exhausted": False,
        },
        {},
        {},
    )
    assert "Added 2 tracks toward target" in capped
    assert "Hit the per-turn insert cap." in capped
