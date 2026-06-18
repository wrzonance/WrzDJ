"""Tests for WrzDJSet agent toolkit (#390)."""

import pytest
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.llm.base import ChatResponse, ToolCall
from app.services.llm.exceptions import NoLlmConfigured
from app.services.setbuilder import agent_history
from app.services.setbuilder.pass1_deterministic import TrackMeta
from app.services.setbuilder.pass2_agent import (
    AgentToolError,
    _explain_warning,
    _tool_display_summary,
    _track_summary,
    apply_tool_call,
    chat_with_agent,
    critique_set,
)


def _chat_then_critique(chat_calls, critique_input, counter=None):
    """Fake Gateway.dispatch: chat turn first, real critique on force_tool."""

    async def fake_dispatch(*args, **kwargs):
        if counter is not None:
            counter["count"] += 1
        request = args[2]
        if getattr(request, "force_tool", None) == "critique_set":
            return ChatResponse(
                stop_reason="tool_use",
                tool_calls=[ToolCall(id="real-crit", name="critique_set", input=critique_input)],
            )
        return ChatResponse(text="", stop_reason="tool_use", tool_calls=chat_calls)

    return fake_dispatch


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
async def test_agent_swap_returns_readable_tool_summary(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slots = sorted(set_obj.slots, key=lambda s: s.position)

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            text="",
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

    assert result.message == "Swapped slot 1 Track 0 - Artist 0 with slot 2 Track 1 - Artist 1."
    assert result.tool_calls[0].display_summary == result.message


@pytest.mark.asyncio
async def test_agent_preserves_non_empty_gateway_text(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    slots = sorted(set_obj.slots, key=lambda s: s.position)

    async def fake_dispatch(*args, **kwargs):
        return ChatResponse(
            text="  I swapped the opener.\n",
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

    assert result.message == "  I swapped the opener.\n"


def test_tool_display_summary_handles_reorder_and_fallback():
    before = {
        10: {
            "slot_id": 10,
            "position": 0,
            "track_id": "tidal:0",
            "label": "Track 0 - Artist 0",
            "target_energy": None,
        }
    }

    assert (
        _tool_display_summary(
            "reorder_slot",
            {"slot_id": 10},
            {"position": 2},
            before,
            {},
        )
        == "Moved Track 0 - Artist 0 from slot 1 to slot 3."
    )
    assert _tool_display_summary("unknown_tool", {}, {}, {}, {}) == "Unknown tool."


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


def test_agent_decode_json_list_filters_non_dict_entries():
    raw = '[{"name":"swap_slots"},"x",1,{"name":"analyze_transition"}]'

    decoded = agent_history.decode_json_list(raw)

    assert decoded == [{"name": "swap_slots"}, {"name": "analyze_transition"}]


def test_agent_decode_json_list_handles_invalid_payloads():
    assert agent_history.decode_json_list(None) == []
    assert agent_history.decode_json_list("{bad json") == []
    assert agent_history.decode_json_list('{"name":"swap_slots"}') == []
    assert agent_history.decode_json_list('["x",1]') == []


def test_agent_context_excludes_compacted_recent_messages(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    session = agent_history.get_or_create_session(db, set_obj.id, test_user.id)
    persisted = [
        agent_history.append_message(db, session, role="user", content=f"turn {idx}")
        for idx in range(5)
    ]
    session.context_summary = "Earlier compacted turns."
    session.compacted_through_message_id = persisted[2].id
    db.commit()

    messages = agent_history.context_messages(db, set_obj, session, "current", recent_limit=10)

    assert [m.content for m in messages[-3:]] == ["turn 3", "turn 4", "current"]
    assert "turn 2" not in [m.content for m in messages]


@pytest.mark.asyncio
async def test_agent_critique_set_returns_real_llm_critique(
    monkeypatch, db: Session, test_user: User
):
    set_obj = _mk_set_with_tracks(db, test_user)
    fake = _chat_then_critique(
        chat_calls=[ToolCall(id="chat-crit", name="critique_set", input={})],
        critique_input={
            "overall_grade": "A-",
            "summary": "Tight arc, strong peak.",
            "flags": [{"type": "banger_buried", "slot_position": 1}],
        },
    )
    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake)

    result = await chat_with_agent(db, test_user, set_obj, message="Critique this set")

    call = result.tool_calls[0]
    assert call.name == "critique_set"
    assert call.result["overall_grade"] == "A-"
    assert call.result["flags"][0]["type"] == "banger_buried"
    assert "A-" in call.display_summary


@pytest.mark.asyncio
async def test_agent_critique_dispatches_llm_once_per_turn(
    monkeypatch, db: Session, test_user: User
):
    set_obj = _mk_set_with_tracks(db, test_user)
    counter = {"count": 0}
    fake = _chat_then_critique(
        chat_calls=[
            ToolCall(id="c1", name="critique_set", input={}),
            ToolCall(id="c2", name="critique_set", input={}),
        ],
        critique_input={"overall_grade": "B", "summary": "", "flags": []},
        counter=counter,
    )
    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake)

    result = await chat_with_agent(db, test_user, set_obj, message="Critique twice")

    assert len(result.tool_calls) == 2
    assert counter["count"] == 2  # one chat dispatch + one critique dispatch (deduped)
    assert all(c.result["overall_grade"] == "B" for c in result.tool_calls)


@pytest.mark.asyncio
async def test_agent_critique_degrades_when_no_llm(monkeypatch, db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    async def fake_dispatch(*args, **kwargs):
        request = args[2]
        if getattr(request, "force_tool", None) == "critique_set":
            raise NoLlmConfigured("no connector")
        return ChatResponse(
            text="",
            stop_reason="tool_use",
            tool_calls=[ToolCall(id="chat-crit", name="critique_set", input={})],
        )

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

    result = await chat_with_agent(db, test_user, set_obj, message="Critique this set")

    call = result.tool_calls[0]
    assert call.result["available"] is False
    assert "slot_count" in call.result  # static fallback fields present


@pytest.mark.asyncio
async def test_agent_critique_leaves_event_requests_untouched(
    monkeypatch, db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_tracks(db, test_user)
    before_count = db.query(Request).count()
    before_title = test_request.song_title
    fake = _chat_then_critique(
        chat_calls=[ToolCall(id="chat-crit", name="critique_set", input={})],
        critique_input={"overall_grade": "C", "summary": "ok", "flags": []},
    )
    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake)

    await chat_with_agent(db, test_user, set_obj, message="Critique this set")

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_tool_display_summary_includes_transition_warnings():
    summary = _tool_display_summary(
        "analyze_transition",
        {},
        {"position": 2, "score": 68.0, "warnings": ["bpm_jump", "key_clash"]},
        {},
        {},
    )

    assert "slot 3" in summary
    assert "68" in summary
    assert "bpm jump" in summary
    assert "key clash" in summary


def test_tool_display_summary_transition_omits_empty_warnings():
    summary = _tool_display_summary(
        "analyze_transition",
        {},
        {"position": 1, "score": 90.0, "warnings": []},
        {},
        {},
    )

    assert summary == "Analyzed transition into slot 2: 90."


def _meta(**overrides) -> TrackMeta:
    base = dict(
        pool_id=1,
        slot_track_id="tidal:x",
        title="T",
        artist="A",
        bpm=124.0,
        key="8A",
        energy=6,
    )
    base.update(overrides)
    return TrackMeta(**base)


def test_explain_warning_key_clash_cites_both_keys():
    prev = _meta(key="8A")
    curr = _meta(key="2A")
    detail = _explain_warning("key_clash", prev, curr)
    assert "8A" in detail and "2A" in detail


def test_explain_warning_mood_shift_cites_both_moods():
    prev = _meta(mood="dark")
    curr = _meta(mood="euphoric")
    detail = _explain_warning("mood_shift", prev, curr)
    assert "dark" in detail and "euphoric" in detail


def test_explain_warning_handles_missing_prev_and_fields():
    detail = _explain_warning("bpm_jump", None, _meta(bpm=None))
    assert "unknown" in detail
    # Unknown codes fall back to a readable phrase.
    assert _explain_warning("some_new_code", None, _meta()) == "some new code"


def test_track_summary_handles_none():
    assert _track_summary(None) is None
    assert _track_summary(_meta(title="Hi"))["title"] == "Hi"


def test_tool_display_summary_explain_transition_lists_details():
    summary = _tool_display_summary(
        "explain_transition",
        {},
        {
            "position": 2,
            "score": 60.0,
            "explanations": [{"code": "bpm_jump", "detail": "Big tempo gap: 124 into 150."}],
        },
        {},
        {},
    )

    assert "slot 3" in summary
    assert "Big tempo gap" in summary


def test_tool_display_summary_explain_transition_clean():
    summary = _tool_display_summary(
        "explain_transition",
        {},
        {"position": 1, "score": 92.0, "explanations": []},
        {},
        {},
    )

    assert summary == "Explained transition into slot 2. No transition issues."


def _mk_set_with_warned_transition(db: Session, user: User) -> Set:
    """A two-slot set whose transition trips bpm_jump + repeat_artist warnings."""
    set_obj = Set(owner_id=user.id, name="Warned Set", key_strictness=1.0)
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
                track_id="tidal:a",
                title="Opener",
                artist="DJ Same",
                bpm=124,
                key="8A",
                camelot="8A",
                energy=8,
                duration_sec=210,
                dedupe_sig="sig-a",
            ),
            SetPoolTrack(
                set_id=set_obj.id,
                source_id=source.id,
                track_id="tidal:b",
                title="Follower",
                artist="DJ Same",
                bpm=150,
                key="2A",
                camelot="2A",
                energy=3,
                duration_sec=210,
                dedupe_sig="sig-b",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            SetSlot(set_id=set_obj.id, position=0, track_id="tidal:a"),
            SetSlot(set_id=set_obj.id, position=1, track_id="tidal:b"),
        ]
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def test_explain_transition_returns_grounded_explanations(db: Session, test_user: User):
    set_obj = _mk_set_with_warned_transition(db, test_user)

    result, positions = apply_tool_call(db, set_obj, "explain_transition", {"position": 1})

    assert positions == set()
    assert result["position"] == 1
    assert isinstance(result["score"], float)
    codes = {item["code"] for item in result["explanations"]}
    assert "bpm_jump" in codes
    assert "repeat_artist" in codes
    by_code = {item["code"]: item["detail"] for item in result["explanations"]}
    # bpm_jump explanation cites both real BPM values.
    assert "124" in by_code["bpm_jump"]
    assert "150" in by_code["bpm_jump"]
    # repeat_artist explanation names the shared artist.
    assert "DJ Same" in by_code["repeat_artist"]
    # Compact prev/curr summary carries the two tracks' real fields.
    assert result["prev"]["title"] == "Opener"
    assert result["curr"]["title"] == "Follower"
    assert result["prev"]["bpm"] == 124
    assert result["curr"]["bpm"] == 150


def test_explain_transition_clean_transition_has_no_issues(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    result, positions = apply_tool_call(db, set_obj, "explain_transition", {"position": 1})

    assert positions == set()
    assert result["explanations"] == []
    assert result["prev"]["title"] == "Track 0"
    assert result["curr"]["title"] == "Track 1"


def test_explain_transition_rejects_out_of_range_position(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)

    with pytest.raises(AgentToolError):
        apply_tool_call(db, set_obj, "explain_transition", {"position": 0})
    with pytest.raises(AgentToolError):
        apply_tool_call(db, set_obj, "explain_transition", {"position": 99})


def test_explain_transition_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_warned_transition(db, test_user)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(db, set_obj, "explain_transition", {"position": 1})

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title
