"""Tests for per-DJ SetBuilder taste profiles from TrackVibeOverride rows (#409)."""

import json
from datetime import timedelta

from sqlalchemy.orm import Session

from app.api import setbuilder as setbuilder_api
from app.core.time import utcnow
from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.set_taste_profile import SetTasteProfileReset
from app.models.track_vibe import (
    TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
    TRACK_VIBE_SOURCE_UPVOTE,
    TrackVibe,
    TrackVibeOverride,
)
from app.models.user import User
from app.services.setbuilder.pass1_deterministic import build_set, recompute_transition_scores
from app.services.setbuilder.pass2_agent import _set_context
from app.services.setbuilder.taste_profile import (
    ENERGY_ADJUSTMENT_CAP,
    MIN_TASTE_SAMPLES,
    build_taste_profile,
)
from app.services.setbuilder.vibe_enrichment import PROMPT_VERSION, SCHEMA_VERSION


def _override(
    db: Session,
    user_id: int,
    idx: int,
    *,
    energy: int | None,
    energy_was: int | None,
    mood: str | None = None,
    source: str = TRACK_VIBE_SOURCE_EXPLICIT_EDIT,
    created_at=None,
) -> TrackVibeOverride:
    row = TrackVibeOverride(
        track_id=f"taste:{idx}",
        user_id=user_id,
        energy_override=energy,
        energy_was=energy_was,
        mood_override=mood,
        source=source,
        created_at=created_at or utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_set(db: Session, user: User, *, duration: int = 210) -> Set:
    set_obj = Set(owner_id=user.id, name="Taste Set", target_duration_sec=duration)
    db.add(set_obj)
    db.commit()
    db.refresh(set_obj)
    return set_obj


def _mk_source(db: Session, set_obj: Set) -> SetPoolSource:
    source = SetPoolSource(set_id=set_obj.id, kind="manual", label="Manual")
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _mk_pool_track(
    db: Session,
    set_obj: Set,
    source: SetPoolSource,
    *,
    idx: int,
    track_id: str,
) -> SetPoolTrack:
    track = SetPoolTrack(
        set_id=set_obj.id,
        source_id=source.id,
        track_id=track_id,
        title=f"Track {idx}",
        artist=f"Artist {idx}",
        bpm=124.0,
        key="8A",
        camelot="8A",
        energy=None,
        duration_sec=210,
        dedupe_sig=f"sig-{idx}",
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def _llm_energy(db: Session, track_id: str, *, energy: int, mood: str | None = None) -> None:
    db.add(
        TrackVibe(
            track_id=track_id,
            energy=energy,
            mood=mood,
            confidence=0.9,
            llm_provider="anthropic_apikey",
            llm_model="claude-haiku-4-5",
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
        )
    )
    db.commit()


def test_profile_requires_min_samples_and_caps_energy_bias(db: Session, test_user: User):
    for idx in range(MIN_TASTE_SAMPLES - 1):
        _override(db, test_user.id, idx, energy=10, energy_was=3, mood="Peak")

    inactive = build_taste_profile(db, test_user.id)

    assert inactive.sample_count == MIN_TASTE_SAMPLES - 1
    assert inactive.active is False
    assert inactive.average_energy_delta == 7.0
    assert inactive.energy_adjustment == 0.0

    _override(db, test_user.id, 99, energy=10, energy_was=3, mood="Peak")
    active = build_taste_profile(db, test_user.id)

    assert active.sample_count == MIN_TASTE_SAMPLES
    assert active.active is True
    assert active.average_energy_delta == 7.0
    assert active.energy_adjustment == ENERGY_ADJUSTMENT_CAP
    assert active.top_moods[0].mood == "Peak"
    assert active.top_moods[0].count == MIN_TASTE_SAMPLES
    assert "+1.5" in active.summary


def test_profile_ignores_upvotes_and_reset_excludes_older_history(db: Session, test_user: User):
    older = utcnow() - timedelta(days=2)
    newer = utcnow()
    for idx in range(MIN_TASTE_SAMPLES):
        _override(db, test_user.id, idx, energy=10, energy_was=4, mood="old", created_at=older)
    _override(
        db,
        test_user.id,
        100,
        energy=10,
        energy_was=4,
        mood="upvote",
        source=TRACK_VIBE_SOURCE_UPVOTE,
        created_at=newer,
    )
    db.add(SetTasteProfileReset(user_id=test_user.id, reset_at=utcnow() - timedelta(days=1)))
    db.commit()
    for idx in range(MIN_TASTE_SAMPLES):
        _override(
            db,
            test_user.id,
            200 + idx,
            energy=2,
            energy_was=4,
            mood="cooldown",
            created_at=newer,
        )

    profile = build_taste_profile(db, test_user.id)

    assert db.query(TrackVibeOverride).count() == (MIN_TASTE_SAMPLES * 2) + 1
    assert profile.sample_count == MIN_TASTE_SAMPLES
    assert profile.average_energy_delta == -2.0
    assert profile.energy_adjustment == -1.5
    assert profile.top_moods[0].mood == "cooldown"


def test_pass1_uses_taste_adjusted_energy_when_profile_is_active(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user)
    source = _mk_source(db, set_obj)
    first = _mk_pool_track(db, set_obj, source, idx=0, track_id="tidal:first")
    second = _mk_pool_track(db, set_obj, source, idx=1, track_id="tidal:second")
    assert first.id < second.id
    _llm_energy(db, "tidal:first", energy=8)
    _llm_energy(db, "tidal:second", energy=6)
    for idx in range(MIN_TASTE_SAMPLES):
        _override(db, test_user.id, idx, energy=8, energy_was=6)

    result = build_set(db, set_obj)

    assert result.slot_count == 1
    assert result.slots[0].track_id == "tidal:second"


def test_pass1_ignores_taste_profile_below_sample_gate(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user)
    source = _mk_source(db, set_obj)
    _mk_pool_track(db, set_obj, source, idx=0, track_id="tidal:first")
    _mk_pool_track(db, set_obj, source, idx=1, track_id="tidal:second")
    _llm_energy(db, "tidal:first", energy=8)
    _llm_energy(db, "tidal:second", energy=6)
    for idx in range(MIN_TASTE_SAMPLES - 1):
        _override(db, test_user.id, idx, energy=8, energy_was=6)

    result = build_set(db, set_obj)

    assert result.slot_count == 1
    assert result.slots[0].track_id == "tidal:first"


def test_pass1_continues_with_neutral_profile_when_profile_read_fails(
    monkeypatch, db: Session, test_user: User
):
    set_obj = _mk_set(db, test_user)
    source = _mk_source(db, set_obj)
    _mk_pool_track(db, set_obj, source, idx=0, track_id="tidal:first")
    monkeypatch.setattr(
        "app.services.setbuilder.pass1_deterministic.taste_profile_service.build_taste_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("profile unavailable")),
    )

    result = build_set(db, set_obj)

    assert result.slot_count == 1
    assert result.slots[0].track_id == "tidal:first"


def test_transition_rescore_continues_with_neutral_profile_when_profile_read_fails(
    monkeypatch, db: Session, test_user: User
):
    set_obj = _mk_set(db, test_user)
    source = _mk_source(db, set_obj)
    track = _mk_pool_track(db, set_obj, source, idx=0, track_id="tidal:first")
    slot = SetSlot(set_id=set_obj.id, position=0, track_id=track.track_id)
    db.add(slot)
    db.commit()
    db.refresh(slot)
    monkeypatch.setattr(
        "app.services.setbuilder.pass1_deterministic.taste_profile_service.build_taste_profile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("profile unavailable")),
    )

    scores = recompute_transition_scores(db, set_obj)

    assert scores[0].position == 0
    assert scores[0].score == 100.0


def test_pass2_context_includes_compact_taste_summary(db: Session, test_user: User):
    set_obj = _mk_set(db, test_user)
    for idx in range(MIN_TASTE_SAMPLES):
        _override(db, test_user.id, idx, energy=8, energy_was=6, mood="Peak")

    context = json.loads(_set_context(db, set_obj))

    assert context["taste_profile"]["active"] is True
    assert context["taste_profile"]["sample_count"] == MIN_TASTE_SAMPLES
    assert "Peak" in context["taste_profile"]["summary"]
    assert "+1.5" in context["taste_profile"]["summary"]


def test_taste_profile_api_get_and_reset_keeps_override_rows(db: Session, test_user: User):
    for idx in range(MIN_TASTE_SAMPLES):
        _override(db, test_user.id, idx, energy=8, energy_was=6, mood="Peak")

    profile = setbuilder_api.get_taste_profile(request=None, db=db, current_user=test_user)

    assert profile.active is True
    assert profile.sample_count == MIN_TASTE_SAMPLES

    reset = setbuilder_api.reset_taste_profile(request=None, db=db, current_user=test_user)

    assert reset.active is False
    assert reset.sample_count == 0
    assert db.query(TrackVibeOverride).count() == MIN_TASTE_SAMPLES
