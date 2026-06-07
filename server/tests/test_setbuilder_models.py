"""Model + constraint tests for WrzDJSet Phase 0 tables."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.set import Set, SetCollaborator, SetCurvePoint, SetSlot
from app.models.track_vibe import TrackVibe, TrackVibeOverride


def _make_user(db):
    from app.models.user import User
    from app.services.auth import get_password_hash

    user = User(username="setowner", password_hash=get_password_hash("x" * 12), role="dj")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


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


def test_set_persists_with_defaults(db):
    user = _make_user(db)
    s = Set(owner_id=user.id, name="Friday Wedding")
    db.add(s)
    db.commit()
    db.refresh(s)
    assert s.id is not None
    assert s.status == "draft"
    assert s.sharing_mode == "private"
    assert s.key_strictness == 0.2
    assert s.event_id is None
    assert s.created_at is not None
    assert s.updated_at is not None


def test_set_slot_cascade_delete(db):
    user = _make_user(db)
    s = Set(owner_id=user.id, name="Set")
    db.add(s)
    db.commit()
    db.add(SetSlot(set_id=s.id, position=0, track_id="tidal:1"))
    db.add(SetCurvePoint(set_id=s.id, position_sec=0, energy=3))
    db.add(SetCollaborator(set_id=s.id, user_id=user.id, role="editor", invited_by=user.id))
    db.commit()
    assert db.query(SetSlot).count() == 1
    assert db.query(SetCurvePoint).count() == 1
    assert db.query(SetCollaborator).count() == 1

    db.delete(s)
    db.commit()
    assert db.query(SetSlot).count() == 0
    assert db.query(SetCurvePoint).count() == 0
    assert db.query(SetCollaborator).count() == 0


def test_set_slot_locked_defaults_false(db):
    user = _make_user(db)
    s = Set(owner_id=user.id, name="Set")
    db.add(s)
    db.commit()
    slot = SetSlot(set_id=s.id, position=0, track_id="tidal:1")
    db.add(slot)
    db.commit()
    db.refresh(slot)
    assert slot.locked is False
    assert slot.transition_score is None


def test_set_slot_empty_track_allowed(db):
    user = _make_user(db)
    s = Set(owner_id=user.id, name="Set")
    db.add(s)
    db.commit()
    slot = SetSlot(set_id=s.id, position=0)
    db.add(slot)
    db.commit()
    db.refresh(slot)
    assert slot.track_id is None
