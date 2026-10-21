"""Tests for Pass 2 slot replacement tools."""

import pytest
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.user import User
from app.services.llm.base import ChatResponse, ToolCall
from app.services.setbuilder.agent.pass2_agent import (
    AgentToolError,
    _tool_display_summary,
    apply_tool_call,
    chat_with_agent,
)
from tests.setbuilder_agent_test_helpers import _mk_set_with_tracks, _pool_track_by_track_id


def test_tool_display_summary_replace_slot():
    summary = _tool_display_summary(
        "replace_slot",
        {"slot_id": 1, "pool_track_id": 9},
        {"slot_id": 1, "pool_track_id": 9},
        {1: {"position": 0, "label": "Old - A"}},
        {1: {"position": 0, "label": "New - B"}},
    )

    assert summary == "Replaced Old - A with New - B at slot 1."


def test_replace_slot_swaps_track_in_place(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    opener = sorted(set_obj.slots, key=lambda s: s.position)[0]
    second = sorted(set_obj.slots, key=lambda s: s.position)[1]
    # tidal:2 is in the pool but not yet placed in any slot.
    replacement = _pool_track_by_track_id(set_obj, "tidal:2")

    result, positions = apply_tool_call(
        db,
        set_obj,
        "replace_slot",
        {
            "slot_id": opener.id,
            "pool_track_id": replacement.id,
            "rationale": "Open with a stronger track.",
        },
    )

    db.refresh(opener)
    db.refresh(second)
    assert result == {"slot_id": opener.id, "pool_track_id": replacement.id}
    assert positions == {0}
    # Same position, new track id derived the way the insert tools derive it.
    assert opener.position == 0
    assert opener.track_id == "tidal:2"
    # The other slot is untouched.
    assert second.position == 1
    assert second.track_id == "tidal:1"


def test_replace_slot_rejects_locked_slot(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    opener = sorted(set_obj.slots, key=lambda s: s.position)[0]
    opener.locked = True
    db.commit()
    replacement = _pool_track_by_track_id(set_obj, "tidal:2")
    before_track_id = opener.track_id

    with pytest.raises(AgentToolError, match="[Ll]ocked"):
        apply_tool_call(
            db,
            set_obj,
            "replace_slot",
            {
                "slot_id": opener.id,
                "pool_track_id": replacement.id,
                "rationale": "Try to replace a pinned track.",
            },
        )

    db.refresh(opener)
    assert opener.track_id == before_track_id


def test_replace_slot_rejects_foreign_pool_track(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    other = _mk_set_with_tracks(db, test_user)
    opener = sorted(set_obj.slots, key=lambda s: s.position)[0]
    foreign = _pool_track_by_track_id(other, "tidal:2")

    with pytest.raises(AgentToolError, match="Pool track not found"):
        apply_tool_call(
            db,
            set_obj,
            "replace_slot",
            {
                "slot_id": opener.id,
                "pool_track_id": foreign.id,
                "rationale": "Pull a track from another set.",
            },
        )


def test_replace_slot_rejects_foreign_slot(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    other = _mk_set_with_tracks(db, test_user)
    foreign_slot = sorted(other.slots, key=lambda s: s.position)[0]
    replacement = _pool_track_by_track_id(set_obj, "tidal:2")

    with pytest.raises(AgentToolError, match="Slot not found"):
        apply_tool_call(
            db,
            set_obj,
            "replace_slot",
            {
                "slot_id": foreign_slot.id,
                "pool_track_id": replacement.id,
                "rationale": "Replace a slot from another set.",
            },
        )


@pytest.mark.asyncio
async def test_replace_slot_requires_rationale(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    opener = sorted(set_obj.slots, key=lambda s: s.position)[0]
    replacement = _pool_track_by_track_id(set_obj, "tidal:2")

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="replace-1",
                    name="replace_slot",
                    input={"slot_id": opener.id, "pool_track_id": replacement.id},
                )
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.agent.pass2_agent.Gateway.dispatch", fake_dispatch)

    with pytest.raises(AgentToolError, match="rationale"):
        await chat_with_agent(db, test_user, set_obj, message="Replace the opener")


def test_replace_slot_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_tracks(db, test_user)
    opener = sorted(set_obj.slots, key=lambda s: s.position)[0]
    replacement = _pool_track_by_track_id(set_obj, "tidal:2")
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(
        db,
        set_obj,
        "replace_slot",
        {
            "slot_id": opener.id,
            "pool_track_id": replacement.id,
            "rationale": "Swap the opener; the request queue must stay untouched.",
        },
    )

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title
