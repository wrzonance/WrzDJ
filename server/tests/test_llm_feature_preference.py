"""Tests for per-feature connector preference (issue #337)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.llm_connector import LlmConnector
from app.models.llm_feature_preference import KNOWN_FEATURES, LlmFeaturePreference
from app.models.user import User
from app.services.auth import get_password_hash


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
