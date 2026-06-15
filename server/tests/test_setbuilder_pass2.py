"""Tests for WrzDJSet agent toolkit (#390)."""

import pytest
from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.llm.base import ChatResponse, ToolCall
from app.services.setbuilder import agent_history
from app.services.setbuilder.pass2_agent import (
    AgentToolError,
    chat_with_agent,
    critique_set,
)


def _mk_set_with_tracks(db: Session, user: User) -> Set:
    set_obj = Set(owner_id=user.id, name="Agent Set", target_duration_sec=7 * 60)
    db.add(set_obj)
    db.flush()
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.flush()
    tracks = [
        SetPoolTrack(
            set_id=set_obj.id,
            source_id=source.id,
            track_id=f"tidal:{idx}",
            title=f"Track {idx}",
            artist=f"Artist {idx}",
            bpm=124 + idx,
            key="8A",
            camelot="8A",
            energy=5 + idx,
            duration_sec=210,
            dedupe_sig=f"sig-{idx}",
        )
        for idx in range(3)
    ]
    db.add_all(tracks)
    db.flush()
    db.add_all(
        [
            SetSlot(set_id=set_obj.id, position=0, track_id="tidal:0"),
            SetSlot(set_id=set_obj.id, position=1, track_id="tidal:1"),
        ]
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


@pytest.mark.asyncio
async def test_critique_set_parses_structured_gateway_tool(
    monkeypatch, db: Session, test_user: User
):
    set_obj = _mk_set_with_tracks(db, test_user)

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="critique-1",
                    name="critique_set",
                    input={
                        "overall_grade": "B+",
                        "summary": "Strong arc.",
                        "flags": [{"type": "transition_brilliant", "slot_position": 1}],
                    },
                )
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    result = await critique_set(db, test_user, set_obj)

    assert result.overall_grade == "B+"
    assert result.flags[0].type == "transition_brilliant"


@pytest.mark.asyncio
async def test_agent_mutation_requires_rationale(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(id="swap-1", name="swap_slots", input={"slot_a_id": 1, "slot_b_id": 2})
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    with pytest.raises(AgentToolError, match="rationale"):
        await chat_with_agent(db, test_user, set_obj, message="Swap them")


@pytest.mark.asyncio
async def test_agent_swap_applies_and_returns_rationale(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slots = sorted(set_obj.slots, key=lambda s: s.position)

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            text="I swapped the opener.",
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="swap-1",
                    name="swap_slots",
                    input={
                        "slot_a_id": slots[0].id,
                        "slot_b_id": slots[1].id,
                        "rationale": "Start with the stronger groove.",
                    },
                )
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    result = await chat_with_agent(db, test_user, set_obj, message="Swap the first two")

    assert result.tool_calls[0].args["slot_a_id"] == slots[0].id
    assert result.tool_calls[0].rationale == "Start with the stronger groove."
    assert [s.track_id for s in result.slots] == ["tidal:1", "tidal:0"]
    assert result.affected_transition_scores


@pytest.mark.asyncio
async def test_agent_remove_does_not_shift_locked_slots(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slots = sorted(set_obj.slots, key=lambda s: s.position)
    slots[1].locked = True
    db.commit()

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="remove-1",
                    name="remove_slot",
                    input={
                        "slot_id": slots[0].id,
                        "rationale": "Clear space without moving the pinned track.",
                    },
                )
            ],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    with pytest.raises(AgentToolError, match="locked"):
        await chat_with_agent(db, test_user, set_obj, message="Remove the opener")


def test_agent_context_uses_summary_and_recent_messages(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    session = agent_history.get_or_create_session(db, set_obj.id, test_user.id)
    session.context_summary = "Earlier: user asked for a softer cocktail section."
    for idx in range(8):
        agent_history.append_message(
            db,
            session,
            role="user" if idx % 2 == 0 else "assistant",
            content=f"turn {idx}",
        )

    messages = agent_history.context_messages(db, set_obj, session, "new request", recent_limit=3)

    assert "Earlier: user asked" in messages[1].content
    assert [m.content for m in messages[-4:]] == ["turn 5", "turn 6", "turn 7", "new request"]


def test_agent_compaction_updates_summary_without_gateway(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    session = agent_history.get_or_create_session(db, set_obj.id, test_user.id)
    for idx in range(agent_history.COMPACTION_TURN_THRESHOLD + 1):
        agent_history.append_message(
            db,
            session,
            role="assistant",
            content=f"assistant turn {idx}",
            display_summary=f"Moved Track {idx}.",
        )

    changed = agent_history.compact_if_needed(db, session)

    assert changed is True
    assert session.context_summary is not None
    assert "Moved Track 0." in session.context_summary
    assert session.compacted_through_message_id is not None
