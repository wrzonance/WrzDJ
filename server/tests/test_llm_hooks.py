"""Tests for LLM hooks module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.services.recommendation.llm_hooks import (
    LLMSuggestionQuery,
    LLMSuggestionResult,
    generate_llm_suggestions,
    is_llm_available,
)
from app.services.recommendation.scorer import EventProfile


def _add_active_connector(db, user):
    """Insert an active LLM connector owned by ``user`` so the gateway resolver
    (and therefore ``is_llm_available``) sees an available connector."""
    import json

    from app.models.llm_connector import LlmConnector

    connector = LlmConnector(
        user_id=user.id,
        connector_type="anthropic_apikey",
        display_name="Test",
        status="active",
        credentials=json.dumps({"api_key": "sk-ant-fakefakefakefakefakefakefakefakefakefake"}),
        model_hint="claude-haiku-4-5-20251001",
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)
    return connector


def _add_org_default_connector(db):
    """Insert an active ORG-scoped connector and point the system default at it."""
    from app.models.llm_connector import SCOPE_ORG, LlmConnector
    from app.services.system_settings import update_system_settings

    connector = LlmConnector(
        user_id=None,
        scope=SCOPE_ORG,
        connector_type="anthropic_apikey",
        display_name="House",
        status="active",
        credentials="{}",
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)
    update_system_settings(db, llm_default_connector_id=connector.id)
    return connector


class TestIsLLMAvailable:
    """``is_llm_available`` is connector-backed only.

    The legacy ``ANTHROPIC_API_KEY`` env-var fallback was removed in #343, so a
    call without ``db`` can never resolve a connector and returns ``False``.
    """

    def test_returns_false_without_db(self):
        assert is_llm_available() is False

    def test_returns_false_without_db_even_with_actor(self):
        from unittest.mock import MagicMock

        assert is_llm_available(actor=MagicMock()) is False

    def test_available_for_byo_dj_even_when_llm_disabled(self, db: Session, test_user):
        """HEADLINE REGRESSION (spec §2): a DJ's own connector is never blocked
        by ``llm_enabled``.

        Replaces the old-semantics test that asserted the inverse — per
        docs/superpowers/specs/2026-06-09-admin-ai-policy-design.md the
        ``llm_enabled`` toggle governs ONLY the org-fallback path, never BYO
        credentials.
        """
        from app.services.system_settings import update_system_settings

        _add_active_connector(db, test_user)
        update_system_settings(db, llm_enabled=False)
        assert is_llm_available(db, actor=test_user) is True

    def test_unavailable_for_connectorless_dj_when_llm_disabled(self, db: Session, test_user):
        """Org default exists but llm_enabled=False -> connectorless DJ blocked."""
        from app.services.system_settings import update_system_settings

        _add_org_default_connector(db)
        update_system_settings(db, llm_enabled=False)
        assert is_llm_available(db, actor=test_user) is False

    def test_available_via_org_fallback_when_enabled(self, db: Session, test_user):
        """Org default exists and llm_enabled=True -> connectorless DJ available."""
        from app.services.system_settings import update_system_settings

        _add_org_default_connector(db)
        update_system_settings(db, llm_enabled=True)
        assert is_llm_available(db, actor=test_user) is True

    def test_returns_true_when_llm_enabled_and_actor_connector(self, db: Session, test_user):
        """When the actor owns an active connector and llm_enabled is True, returns True."""
        from app.services.system_settings import update_system_settings

        _add_active_connector(db, test_user)
        update_system_settings(db, llm_enabled=True)
        assert is_llm_available(db, actor=test_user) is True

    def test_returns_false_without_connector(self, db: Session, test_user):
        """No connector and no org default -> not available."""
        from app.services.system_settings import update_system_settings

        update_system_settings(db, llm_enabled=True)
        assert is_llm_available(db, actor=test_user) is False


class TestGenerateLLMSuggestions:
    @pytest.mark.asyncio
    @patch("app.services.recommendation.llm_client.call_llm")
    async def test_delegates_to_llm_client(self, mock_call_llm):
        expected = LLMSuggestionResult(
            queries=[LLMSuggestionQuery(search_query="chill house", reasoning="test")],
            raw_response="{}",
        )
        mock_call_llm.return_value = expected

        profile = EventProfile(track_count=5)
        result = await generate_llm_suggestions(profile, "chill vibes", max_queries=3)

        assert result is expected
        mock_call_llm.assert_called_once_with(
            profile,
            "chill vibes",
            3,
            tracks=None,
            rejected_tracks=None,
            currently_playing=None,
            db=None,
            actor=None,
        )

    @pytest.mark.asyncio
    @patch("app.services.recommendation.llm_client.call_llm")
    async def test_passes_tracks_to_llm_client(self, mock_call_llm):
        from app.services.recommendation.scorer import TrackProfile

        expected = LLMSuggestionResult(
            queries=[LLMSuggestionQuery(search_query="house", reasoning="test")],
            raw_response="{}",
        )
        mock_call_llm.return_value = expected

        profile = EventProfile(track_count=1)
        tracks = [TrackProfile(title="Strobe", artist="deadmau5")]
        result = await generate_llm_suggestions(profile, "more like this", tracks=tracks)

        assert result is expected
        mock_call_llm.assert_called_once_with(
            profile,
            "more like this",
            6,
            tracks=tracks,
            rejected_tracks=None,
            currently_playing=None,
            db=None,
            actor=None,
        )


class TestDataClasses:
    def test_suggestion_query_is_frozen(self):
        q = LLMSuggestionQuery(
            search_query="deadmau5 progressive house",
            target_bpm=128.0,
            target_key="8A",
            target_genre="Progressive House",
            reasoning="Matches event profile",
        )
        assert q.search_query == "deadmau5 progressive house"
        with pytest.raises(AttributeError):
            q.search_query = "something else"  # type: ignore[misc]

    def test_suggestion_result_is_frozen(self):
        result = LLMSuggestionResult(
            queries=[LLMSuggestionQuery(search_query="test", reasoning="test reason")],
            raw_response='{"queries": []}',
        )
        assert len(result.queries) == 1
        assert result.raw_response == '{"queries": []}'
        with pytest.raises(AttributeError):
            result.raw_response = "other"  # type: ignore[misc]

    def test_query_defaults(self):
        q = LLMSuggestionQuery(search_query="test")
        assert q.target_bpm is None
        assert q.target_key is None
        assert q.target_genre is None
        assert q.reasoning == ""
