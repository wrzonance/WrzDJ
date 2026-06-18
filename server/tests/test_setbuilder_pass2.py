"""Tests for WrzDJSet agent toolkit (#390)."""

import json

import pytest
from sqlalchemy.orm import Session

from app.models.curve_template import SetCurveTemplate
from app.models.request import Request
from app.models.set import Set, SetCurvePoint, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.track_vibe import (
    TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
    TrackVibe,
    TrackVibeOverride,
)
from app.models.user import User
from app.services.llm.base import ChatResponse, ToolCall
from app.services.llm.exceptions import NoLlmConfigured
from app.services.setbuilder import agent_history, curve
from app.services.setbuilder.pass1_deterministic import TrackMeta
from app.services.setbuilder.pass2_agent import (
    AgentToolError,
    _agent_tools,
    _explain_warning,
    _tool_display_summary,
    _track_summary,
    apply_tool_call,
    chat_with_agent,
    critique_set,
)
from app.services.setbuilder.vibe_enrichment import PROMPT_VERSION, SCHEMA_VERSION


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


def _mk_set_for_summary(db: Session, user: User) -> Set:
    """A set with varied BPM/key/energy so the summary has signal to report."""
    set_obj = Set(owner_id=user.id, name="Summary Set", target_duration_sec=600)
    db.add(set_obj)
    db.flush()
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.flush()
    specs = [
        # (bpm, camelot, key, duration_sec)
        (120.0, "8A", "A minor", 200),
        (124.0, "9A", "E minor", 220),
        (128.0, None, None, 180),  # unknown key -> skipped in key_journey
    ]
    for idx, (bpm, camelot, key, duration) in enumerate(specs):
        db.add(
            SetPoolTrack(
                set_id=set_obj.id,
                source_id=source.id,
                track_id=f"tidal:{idx}",
                title=f"Track {idx}",
                artist=f"Artist {idx}",
                bpm=bpm,
                key=key,
                camelot=camelot,
                energy=5,
                duration_sec=duration,
                dedupe_sig=f"sum-sig-{idx}",
            )
        )
    db.flush()
    db.add_all(
        [
            SetSlot(set_id=set_obj.id, position=0, track_id="tidal:0", target_energy=4.0),
            SetSlot(set_id=set_obj.id, position=1, track_id="tidal:1", target_energy=9.0),
            SetSlot(set_id=set_obj.id, position=2, track_id="tidal:2", target_energy=6.0),
        ]
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def test_summarize_set_reports_duration_bpm_key_and_energy(db: Session, test_user: User):
    set_obj = _mk_set_for_summary(db, test_user)

    result, positions = apply_tool_call(db, set_obj, "summarize_set", {})

    assert positions == set()  # read-only: no affected positions
    assert result["slot_count"] == 3
    assert result["total_duration_sec"] == 600  # 200 + 220 + 180
    assert result["target_duration_sec"] == 600
    assert result["duration_delta_sec"] == 0  # total - target
    assert result["bpm_arc"] == {
        "min": 120.0,
        "max": 128.0,
        "first": 120.0,
        "last": 128.0,
        "mean": 124.0,
    }
    # Unknown key on slot 3 is skipped, order preserved.
    assert result["key_journey"] == ["8A", "9A"]
    assert result["energy_profile"]["values"] == [4.0, 9.0, 6.0]
    assert result["energy_profile"]["peak_position"] == 1  # the 9.0 slot


def test_summarize_set_handles_empty_set(db: Session, test_user: User):
    set_obj = Set(owner_id=test_user.id, name="Empty", target_duration_sec=300)
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)

    result, positions = apply_tool_call(db, set_obj, "summarize_set", {})

    assert positions == set()
    assert result["slot_count"] == 0
    assert result["total_duration_sec"] == 0
    assert result["target_duration_sec"] == 300
    assert result["duration_delta_sec"] == -300
    assert result["bpm_arc"] is None
    assert result["key_journey"] == []
    assert result["energy_profile"] == {"values": [], "peak_position": None}


def test_summarize_set_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_for_summary(db, test_user)
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(db, set_obj, "summarize_set", {})

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_summarize_set_display_summary_is_human_readable():
    summary = _tool_display_summary(
        "summarize_set",
        {},
        {
            "slot_count": 3,
            "total_duration_sec": 600,
            "target_duration_sec": 600,
            "duration_delta_sec": 0,
            "bpm_arc": {"min": 120.0, "max": 128.0, "first": 120.0, "last": 128.0, "mean": 124.0},
            "key_journey": ["8A", "9A"],
            "energy_profile": {"values": [4.0, 9.0, 6.0], "peak_position": 1},
        },
        {},
        {},
    )

    assert "3 slots" in summary
    assert "120" in summary and "128" in summary


def test_tool_display_summary_transition_omits_empty_warnings():
    summary = _tool_display_summary(
        "analyze_transition",
        {},
        {"position": 1, "score": 90.0, "warnings": []},
        {},
        {},
    )

    assert summary == "Analyzed transition into slot 2: 90."


def _seed_llm_vibe(db: Session, track_key: str, **fields) -> TrackVibe:
    """Insert a current-version global LLM vibe row the resolver will trust."""
    vibe = TrackVibe(
        track_id=track_key,
        llm_provider="anthropic",
        llm_model="claude-test",
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        **fields,
    )
    db.add(vibe)
    db.flush()
    return vibe


def test_get_track_vibes_resolves_owner_merged_tags(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    opener = sorted(set_obj.slots, key=lambda s: s.position)[0]
    _seed_llm_vibe(db, "tidal:0", energy=8, mood="dark", confidence=0.9)
    db.add(
        TrackVibeOverride(
            track_id="tidal:0",
            user_id=test_user.id,
            energy_override=6,
            source=TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
        )
    )
    db.commit()

    result, positions = apply_tool_call(db, set_obj, "get_track_vibes", {"slot_id": opener.id})

    assert positions == set()
    assert result["slot_id"] == opener.id
    assert result["has_vibe"] is True
    # Per-field cascade: the DJ's own edit wins energy, LLM cache supplies mood.
    assert result["resolved"] == {
        "energy": 6,
        "energy_source": "own",
        "mood": "dark",
        "mood_source": "llm",
    }


def test_get_track_vibes_empty_when_no_vibe_data(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    opener = sorted(set_obj.slots, key=lambda s: s.position)[0]

    result, positions = apply_tool_call(db, set_obj, "get_track_vibes", {"slot_id": opener.id})

    assert positions == set()
    assert result["has_vibe"] is False
    assert result["resolved"] == {
        "energy": None,
        "energy_source": None,
        "mood": None,
        "mood_source": None,
    }


def test_get_track_vibes_rejects_foreign_slot(db: Session, test_user: User):
    set_obj = _mk_set_with_tracks(db, test_user)
    other = _mk_set_with_tracks(db, test_user)
    foreign_slot = sorted(other.slots, key=lambda s: s.position)[0]

    with pytest.raises(AgentToolError, match="Slot not found"):
        apply_tool_call(db, set_obj, "get_track_vibes", {"slot_id": foreign_slot.id})


def test_tool_display_summary_get_track_vibes_with_tags():
    summary = _tool_display_summary(
        "get_track_vibes",
        {},
        {
            "position": 0,
            "has_vibe": True,
            "resolved": {
                "energy": 6,
                "energy_source": "own",
                "mood": "dark",
                "mood_source": "llm",
            },
        },
        {},
        {},
    )

    assert summary == "Vibe tags for slot 1: energy 6 (own), mood dark (llm)."


def test_tool_display_summary_get_track_vibes_empty():
    summary = _tool_display_summary(
        "get_track_vibes",
        {},
        {
            "position": 2,
            "has_vibe": False,
            "resolved": {
                "energy": None,
                "energy_source": None,
                "mood": None,
                "mood_source": None,
            },
        },
        {},
        {},
    )

    assert summary == "No vibe tags on record for slot 3."


def test_get_track_vibes_leaves_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_tracks(db, test_user)
    opener = sorted(set_obj.slots, key=lambda s: s.position)[0]
    _seed_llm_vibe(db, "tidal:0", energy=7, mood="warm")
    db.commit()
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(db, set_obj, "get_track_vibes", {"slot_id": opener.id})

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def _mk_set_with_pool(db: Session, user: User, tracks: list[dict]) -> Set:
    """Build a set whose pool is described row-by-row (no slots needed).

    Each ``tracks`` entry may carry ``bpm``/``key``/``camelot`` (any may be
    omitted/None) so a test can target specific Camelot keys and BPM bands.
    """
    set_obj = Set(
        owner_id=user.id,
        name="Gap Set",
        bpm_floor=tracks[0].get("bpm_floor") if tracks else None,
        bpm_ceiling=tracks[0].get("bpm_ceiling") if tracks else None,
    )
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
                track_id=f"manual:{idx}",
                title=f"Track {idx}",
                artist=f"Artist {idx}",
                bpm=row.get("bpm"),
                key=row.get("key"),
                camelot=row.get("camelot"),
                dedupe_sig=f"gap-sig-{idx}",
            )
            for idx, row in enumerate(tracks)
        ]
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


def test_analyze_pool_gaps_reports_missing_keys_and_sparse_bands(db: Session, test_user: User):
    # Pool covers only 8A (124) and 9A (132); leaves the other 22 Camelot
    # slots empty and concentrates BPM around two bands.
    set_obj = _mk_set_with_pool(
        db,
        test_user,
        [
            {"camelot": "8A", "bpm": 124},
            {"camelot": "8A", "bpm": 126},
            {"camelot": "9A", "bpm": 132},
            {"key": "F minor", "bpm": None},  # 4A, no BPM
        ],
    )

    gaps, affected = apply_tool_call(db, set_obj, "analyze_pool_gaps", {})

    assert affected == set()
    assert gaps["pool_size"] == 4
    assert gaps["keyed_track_count"] == 4
    assert gaps["bpm_track_count"] == 3
    # 8A, 9A, 4A are present → not missing; everything else is.
    assert "8A" not in gaps["missing_camelot_keys"]
    assert "9A" not in gaps["missing_camelot_keys"]
    assert "4A" not in gaps["missing_camelot_keys"]
    assert "1B" in gaps["missing_camelot_keys"]
    assert len(gaps["missing_camelot_keys"]) == 21
    # Bands cover the observed 124-132 span; the high band (132) has a single
    # track → flagged sparse.
    band_labels = {b["label"] for b in gaps["bpm_bands"]}
    assert any(b["count"] >= 2 for b in gaps["bpm_bands"])
    sparse = {b["label"] for b in gaps["sparse_bands"]}
    assert sparse and sparse <= band_labels


def test_analyze_pool_gaps_empty_pool_is_everything_a_gap(db: Session, test_user: User):
    set_obj = _mk_set_with_pool(db, test_user, [])

    gaps, affected = apply_tool_call(db, set_obj, "analyze_pool_gaps", {})

    assert affected == set()
    assert gaps["pool_size"] == 0
    assert gaps["keyed_track_count"] == 0
    assert gaps["bpm_track_count"] == 0
    assert len(gaps["missing_camelot_keys"]) == 24
    assert gaps["bpm_bands"] == []
    assert gaps["sparse_bands"] == []


def test_analyze_pool_gaps_bands_anchor_to_window_but_keep_every_track(
    db: Session, test_user: User
):
    # Declared window is 120-130, but the pool has tracks below (118) and above
    # (135) it. Bands anchor to the declared window yet widen to cover the
    # outliers, so every BPM-tagged track still lands in a band:
    # sum(band counts) must equal bpm_track_count (no silent drops).
    set_obj = _mk_set_with_pool(
        db,
        test_user,
        [
            {"camelot": "8A", "bpm": 118, "bpm_floor": 120, "bpm_ceiling": 130},
            {"camelot": "8A", "bpm": 124},
            {"camelot": "9A", "bpm": 135},
        ],
    )

    gaps, _ = apply_tool_call(db, set_obj, "analyze_pool_gaps", {})

    assert gaps["bpm_track_count"] == 3
    assert sum(b["count"] for b in gaps["bpm_bands"]) == 3
    labels = {b["label"] for b in gaps["bpm_bands"]}
    assert {"110-120", "120-130", "130-140"} <= labels


def test_analyze_pool_gaps_leaves_event_requests_untouched(
    db: Session, test_user: User, test_request: Request
):
    set_obj = _mk_set_with_pool(
        db,
        test_user,
        [{"camelot": "8A", "bpm": 124}, {"camelot": "9A", "bpm": 128}],
    )
    before_count = db.query(Request).count()
    before_title = test_request.song_title

    apply_tool_call(db, set_obj, "analyze_pool_gaps", {})

    db.refresh(test_request)
    assert db.query(Request).count() == before_count
    assert test_request.song_title == before_title


def test_analyze_pool_gaps_unknown_tool_still_raises():
    # Guards the closed allowlist: an unknown sibling name must not slip through.
    with pytest.raises(AgentToolError, match="Unknown tool"):
        apply_tool_call(None, None, "totally_unknown_tool", {})


def test_tool_display_summary_analyze_pool_gaps():
    summary = _tool_display_summary(
        "analyze_pool_gaps",
        {},
        {
            "pool_size": 4,
            "missing_camelot_keys": ["1A", "1B"],
            "sparse_bands": [{"label": "130-140", "min": 130, "max": 140, "count": 1}],
        },
        {},
        {},
    )

    assert summary == "Analyzed pool gaps over 4 tracks: 2 missing Camelot keys, 1 sparse BPM band."


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


def _mk_set_for_curve(db: Session, user: User, slot_count: int = 4) -> Set:
    """Set with ``slot_count`` slots seeded to a flat baseline target_energy."""
    set_obj = Set(owner_id=user.id, name="Curve Set", target_duration_sec=30 * 60)
    db.add(set_obj)
    db.flush()
    db.add_all(
        [
            SetSlot(set_id=set_obj.id, position=idx, track_id=f"tidal:{idx}", target_energy=5.0)
            for idx in range(slot_count)
        ]
    )
    db.commit()
    db.refresh(set_obj)
    return set_obj


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
    from app.services.setbuilder.pass2_agent import MUTATION_TOOLS

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


def test_tool_display_summary_replace_slot():
    summary = _tool_display_summary(
        "replace_slot",
        {"slot_id": 1, "pool_track_id": 9},
        {"slot_id": 1, "pool_track_id": 9},
        {1: {"position": 0, "label": "Old - A"}},
        {1: {"position": 0, "label": "New - B"}},
    )

    assert summary == "Replaced Old - A with New - B at slot 1."


def _pool_track_by_track_id(set_obj: Set, track_id: str) -> SetPoolTrack:
    return next(t for t in set_obj.pool_tracks if t.track_id == track_id)


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

    monkeypatch.setattr("app.services.setbuilder.pass2_agent.Gateway.dispatch", fake_dispatch)

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
    from app.services.setbuilder.pass2_agent import MUTATION_TOOLS

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
    from app.services.setbuilder.pass2_agent import MUTATION_TOOLS

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
