"""Model + constraint tests for WrzDJSet Phase 0 tables."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.track_vibe import TrackVibe, TrackVibeOverride


def test_track_vibe_persists_with_identity_columns(db):
    vibe = TrackVibe(
        track_id="tidal:12345",
        llm_provider="anthropic",
        llm_model="claude-haiku-4-5",
        prompt_version="v1",
        schema_version="v1",
        energy=7,
        mood="euphoric",
        era="2010s",
        sing_along=True,
        dance_floor=True,
        transitional_role="peak",
        confidence=0.8,
    )
    db.add(vibe)
    db.commit()
    db.refresh(vibe)
    assert vibe.id is not None
    assert vibe.energy == 7
    assert vibe.created_at is not None


def test_track_vibe_unique_constraint(db):
    """UNIQUE(track_id, llm_provider, llm_model, prompt_version, schema_version)."""
    kwargs = dict(
        track_id="tidal:12345",
        llm_provider="anthropic",
        llm_model="claude-haiku-4-5",
        prompt_version="v1",
        schema_version="v1",
    )
    db.add(TrackVibe(**kwargs))
    db.commit()
    db.add(TrackVibe(**kwargs))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_track_vibe_same_track_different_model_allowed(db):
    """Same track under a different model is a distinct cache row."""
    db.add(
        TrackVibe(
            track_id="tidal:12345",
            llm_provider="anthropic",
            llm_model="claude-haiku-4-5",
            prompt_version="v1",
            schema_version="v1",
        )
    )
    db.add(
        TrackVibe(
            track_id="tidal:12345",
            llm_provider="openai",
            llm_model="gpt-5-mini",
            prompt_version="v1",
            schema_version="v1",
        )
    )
    db.commit()
    assert db.query(TrackVibe).count() == 2


def test_track_vibe_override_persists(db):
    override = TrackVibeOverride(
        track_id="tidal:12345",
        user_id=1,
        energy_override=9,
        mood_override="dark",
        energy_was=7,
        mood_was="euphoric",
        source="explicit_edit",
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    assert override.id is not None
    assert override.source == "explicit_edit"
    assert override.created_at is not None
