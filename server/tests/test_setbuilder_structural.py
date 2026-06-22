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
