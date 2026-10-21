"""Tests for Pass 2 read-only inspection and explanation tools."""

import pytest
from sqlalchemy.orm import Session

from app.models.request import Request
from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.track_vibe import (
    TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
    TrackVibe,
    TrackVibeOverride,
)
from app.models.user import User
from app.services.setbuilder.agent.pass2_agent import (
    AgentToolError,
    _explain_warning,
    _tool_display_summary,
    _track_summary,
    apply_tool_call,
)
from app.services.setbuilder.pass1_deterministic import TrackMeta
from app.services.setbuilder.vibe_enrichment import PROMPT_VERSION, SCHEMA_VERSION
from tests.setbuilder_agent_test_helpers import _mk_set_with_tracks


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
                genre=row.get("genre"),
                energy=row.get("energy"),
                duration_sec=row.get("duration_sec"),
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


def test_analyze_pool_gaps_reports_energy_and_genre_coverage(db: Session, test_user: User):
    # 3 tracks: only one carries genre; two carry energy. analyze_pool_gaps must
    # report genre + energy coverage sourced from the resolved pool rows (#542),
    # not the previously-dead energy column.
    set_obj = _mk_set_with_pool(
        db,
        test_user,
        [
            {"camelot": "8A", "bpm": 124, "genre": "House", "energy": 6},
            {"camelot": "9A", "bpm": 128, "energy": 7},
            {"camelot": "10A", "bpm": 130},
        ],
    )

    gaps, affected = apply_tool_call(db, set_obj, "analyze_pool_gaps", {})

    assert affected == set()
    assert gaps["pool_size"] == 3
    assert gaps["genre_track_count"] == 1
    assert gaps["energy_track_count"] == 2
    assert gaps["missing_genre_count"] == 2
    assert gaps["missing_energy_count"] == 1


def test_analyze_pool_gaps_empty_pool_is_everything_a_gap(db: Session, test_user: User):
    set_obj = _mk_set_with_pool(db, test_user, [])

    gaps, affected = apply_tool_call(db, set_obj, "analyze_pool_gaps", {})

    assert affected == set()
    assert gaps["pool_size"] == 0
    assert gaps["keyed_track_count"] == 0
    assert gaps["bpm_track_count"] == 0
    assert gaps["genre_track_count"] == 0
    assert gaps["energy_track_count"] == 0
    assert gaps["missing_genre_count"] == 0
    assert gaps["missing_energy_count"] == 0
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
            "missing_genre_count": 2,
            "missing_energy_count": 3,
        },
        {},
        {},
    )

    assert summary == (
        "Analyzed pool gaps over 4 tracks: 2 missing Camelot keys, 1 sparse BPM band, "
        "2 missing genre, 3 missing energy."
    )


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


def test_analyze_and_explain_transition_resolve_the_same_scoring_context(
    db: Session, test_user: User
):
    set_obj = _mk_set_with_warned_transition(db, test_user)

    analyzed, affected_by_analysis = apply_tool_call(
        db, set_obj, "analyze_transition", {"position": 1}
    )
    explained, affected_by_explanation = apply_tool_call(
        db, set_obj, "explain_transition", {"position": 1}
    )

    assert affected_by_analysis == affected_by_explanation == set()
    assert analyzed["position"] == explained["position"] == 1
    assert analyzed["score"] == explained["score"]
    assert analyzed["warnings"] == [item["code"] for item in explained["explanations"]]
    assert explained["prev"]["title"] == "Opener"
    assert explained["curr"]["title"] == "Follower"


@pytest.mark.parametrize("tool_name", ["analyze_transition", "explain_transition"])
def test_transition_tools_reject_invalid_destination_positions(
    db: Session, test_user: User, tool_name: str
):
    set_obj = _mk_set_with_warned_transition(db, test_user)

    for position in (0, 2, 99):
        with pytest.raises(AgentToolError, match="position must identify a transition destination"):
            apply_tool_call(db, set_obj, tool_name, {"position": position})


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
