"""Tests for per-feature connector preference (issue #337)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.llm_connector import LlmConnector
from app.models.llm_feature_preference import KNOWN_FEATURES, LlmFeaturePreference
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.base import ChatRequest, ChatResponse, Message, TokenUsage
from app.services.llm.gateway import Gateway


@pytest.fixture
def dj_user(db) -> User:
    user = User(
        username="prefdj",
        password_hash=get_password_hash("password123"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_connector(db, user, *, display_name="Pref connector", status="active"):
    row = LlmConnector(
        user_id=user.id,
        connector_type="openai_apikey",
        display_name=display_name,
        status=status,
        credentials=json.dumps({"api_key": "sk-fake-key"}),
        model_hint="gpt-5-mini",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_known_features_contains_recommendation_and_set_builder():
    assert "recommendation" in KNOWN_FEATURES
    assert "set_builder" in KNOWN_FEATURES


def test_unique_constraint_one_pref_per_user_feature(db, dj_user):
    c1 = _make_connector(db, dj_user, display_name="A")
    c2 = _make_connector(db, dj_user, display_name="B")
    db.add(LlmFeaturePreference(user_id=dj_user.id, feature="recommendation", connector_id=c1.id))
    db.commit()
    db.add(LlmFeaturePreference(user_id=dj_user.id, feature="recommendation", connector_id=c2.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_set_feature_preference_upserts(db, dj_user):
    from app.services.llm.connector_storage import (
        get_feature_preferences_for_user,
        set_feature_preference,
    )

    c1 = _make_connector(db, dj_user, display_name="A")
    c2 = _make_connector(db, dj_user, display_name="B")

    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=c1.id)
    db.commit()
    prefs = get_feature_preferences_for_user(db, dj_user.id)
    assert {p.feature: p.connector_id for p in prefs} == {"recommendation": c1.id}

    # Re-set the same feature → replace, not duplicate.
    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=c2.id)
    db.commit()
    prefs = get_feature_preferences_for_user(db, dj_user.id)
    assert {p.feature: p.connector_id for p in prefs} == {"recommendation": c2.id}


def test_clear_feature_preference_removes_row(db, dj_user):
    from app.services.llm.connector_storage import (
        clear_feature_preference,
        get_feature_preferences_for_user,
        set_feature_preference,
    )

    c1 = _make_connector(db, dj_user, display_name="A")
    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=c1.id)
    db.commit()

    removed = clear_feature_preference(db, user_id=dj_user.id, feature="recommendation")
    db.commit()
    assert removed is True
    assert get_feature_preferences_for_user(db, dj_user.id) == []

    # Clearing a non-existent preference is a no-op (returns False).
    assert clear_feature_preference(db, user_id=dj_user.id, feature="recommendation") is False


# ---------- gateway resolution ----------
def _ok_response() -> ChatResponse:
    return ChatResponse(
        text="ok",
        tool_calls=[],
        stop_reason="end_turn",
        usage=TokenUsage(prompt=1, completion=1),
    )


@pytest.mark.asyncio
async def test_gateway_prefers_feature_pin_over_default(db, dj_user):
    from app.services.llm.connector_storage import set_default_for_user, set_feature_preference

    pinned = _make_connector(db, dj_user, display_name="pinned")
    other = _make_connector(db, dj_user, display_name="default")
    set_default_for_user(db, connector=other)  # per-DJ default points elsewhere
    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=pinned.id)
    db.commit()

    captured = {}

    async def fake_chat(self, request):  # noqa: ANN001
        captured["connector_id"] = self.connector.id
        return _ok_response()

    with patch.object(OpenAIApiKeyAdapter, "chat", new=fake_chat):
        await Gateway.dispatch(
            db,
            dj_user,
            ChatRequest(messages=[Message(role="user", content="hi")]),
            purpose="recommendation",
        )
    assert captured["connector_id"] == pinned.id


@pytest.mark.asyncio
async def test_gateway_falls_back_when_pinned_connector_auth_invalid(db, dj_user):
    from app.services.llm.connector_storage import set_default_for_user, set_feature_preference

    pinned = _make_connector(db, dj_user, display_name="pinned", status="auth_invalid")
    fallback = _make_connector(db, dj_user, display_name="fallback")
    set_default_for_user(db, connector=fallback)
    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=pinned.id)
    db.commit()

    captured = {}

    async def fake_chat(self, request):  # noqa: ANN001
        captured["connector_id"] = self.connector.id
        return _ok_response()

    with patch.object(OpenAIApiKeyAdapter, "chat", new=fake_chat):
        await Gateway.dispatch(
            db,
            dj_user,
            ChatRequest(messages=[Message(role="user", content="hi")]),
            purpose="recommendation",
        )
    # Skips the auth_invalid pin, falls through to the per-DJ default.
    assert captured["connector_id"] == fallback.id


@pytest.mark.asyncio
async def test_gateway_falls_back_when_pinned_connector_deleted(db, dj_user):
    """A pin whose connector was deleted is skipped (graceful fallback)."""
    from app.services.llm.connector_storage import set_default_for_user, set_feature_preference

    pinned = _make_connector(db, dj_user, display_name="pinned")
    fallback = _make_connector(db, dj_user, display_name="fallback")
    set_default_for_user(db, connector=fallback)
    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=pinned.id)
    db.commit()

    # Delete the pinned connector directly (simulating a stale FK target). The
    # ON DELETE CASCADE removes the preference row too, so this exercises the
    # "pref row gone" path; the status-flip test above covers "pref points at
    # an inactive connector".
    db.delete(pinned)
    db.commit()

    captured = {}

    async def fake_chat(self, request):  # noqa: ANN001
        captured["connector_id"] = self.connector.id
        return _ok_response()

    with patch.object(OpenAIApiKeyAdapter, "chat", new=fake_chat):
        await Gateway.dispatch(
            db,
            dj_user,
            ChatRequest(messages=[Message(role="user", content="hi")]),
            purpose="recommendation",
        )
    assert captured["connector_id"] == fallback.id


@pytest.mark.asyncio
async def test_gateway_ignores_pin_for_unknown_feature(db, dj_user):
    """A pin set for one feature must not leak into another purpose."""
    from app.services.llm.connector_storage import set_feature_preference

    pinned = _make_connector(db, dj_user, display_name="pinned")
    mru = _make_connector(db, dj_user, display_name="mru")
    set_feature_preference(db, user_id=dj_user.id, feature="recommendation", connector_id=pinned.id)
    db.commit()

    captured = {}

    async def fake_chat(self, request):  # noqa: ANN001
        captured["connector_id"] = self.connector.id
        return _ok_response()

    with patch.object(OpenAIApiKeyAdapter, "chat", new=fake_chat):
        await Gateway.dispatch(
            db,
            dj_user,
            ChatRequest(messages=[Message(role="user", content="hi")]),
            purpose="set_builder",
        )
    # No pin for set_builder → MRU resolution (most recently created here is `mru`).
    assert captured["connector_id"] == mru.id
