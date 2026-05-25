"""Regression: recommendation engine still produces identical output when
routed through the LLM gateway.

The legacy path (no ``db``/``actor``) and the gateway path receive equivalent
mock responses; both must yield identical ``LLMSuggestionResult`` queries.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.llm.base import ChatResponse, TokenUsage, ToolCall
from app.services.recommendation.llm_client import call_llm
from app.services.recommendation.scorer import EventProfile


@pytest.fixture
def event_profile() -> EventProfile:
    return EventProfile(
        avg_bpm=128.0,
        bpm_range=(120.0, 134.0),
        dominant_keys=["8A", "9A"],
        dominant_genres=["Tech House"],
        track_count=10,
    )


GATEWAY_RESPONSE = ChatResponse(
    text="",
    tool_calls=[
        ToolCall(
            id="tu_1",
            name="search_queries",
            input={
                "queries": [
                    {
                        "search_query": "deadmau5 progressive house",
                        "target_bpm": 128.0,
                        "target_key": "8A",
                        "target_genre": "Progressive House",
                        "reasoning": "Anchor track style",
                    },
                    {
                        "search_query": "eric prydz",
                        "reasoning": "Similar artist",
                    },
                ]
            },
        )
    ],
    stop_reason="tool_use",
    usage=TokenUsage(prompt=50, completion=20),
)


def _legacy_anthropic_response():
    """Return a mock that mimics the Anthropic SDK response shape."""
    from types import SimpleNamespace

    tool_block = SimpleNamespace(
        type="tool_use",
        name="search_queries",
        input=GATEWAY_RESPONSE.tool_calls[0].input,
    )
    return SimpleNamespace(content=[tool_block])


@pytest.mark.asyncio
async def test_gateway_path_matches_legacy_path_output(db, test_user, event_profile):
    """The same model output, routed via gateway vs legacy env-var, yields the
    same canonical ``LLMSuggestionResult``.
    """
    # Insert a connector for the actor so the gateway has something to resolve.
    from app.models.llm_connector import LlmConnector

    connector = LlmConnector(
        user_id=test_user.id,
        connector_type="anthropic_apikey",
        display_name="Test",
        status="active",
        credentials=json.dumps({"api_key": "sk-ant-fakefakefakefakefakefakefakefakefakefake"}),
        model_hint="claude-haiku-4-5-20251001",
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)

    # Gateway path: mock the adapter's chat method directly.
    with patch(
        "app.services.llm.adapters.anthropic_apikey.AnthropicApiKeyAdapter.chat",
        new=AsyncMock(return_value=GATEWAY_RESPONSE),
    ):
        gateway_result = await call_llm(
            event_profile,
            "deeper progressive house",
            db=db,
            actor=test_user,
        )

    # Legacy path: mock AsyncAnthropic at module level.
    legacy_mock = _legacy_anthropic_response()
    with (
        patch("app.services.recommendation.llm_client.AsyncAnthropic") as client_cls,
        patch("app.services.recommendation.llm_client.get_settings") as settings_mock,
    ):
        settings_mock.return_value.anthropic_api_key = "sk-ant-fake"
        settings_mock.return_value.anthropic_model = "claude-haiku-4-5-20251001"
        settings_mock.return_value.anthropic_max_tokens = 1024
        settings_mock.return_value.anthropic_timeout_seconds = 15
        client_inst = client_cls.return_value
        client_inst.messages.create = AsyncMock(return_value=legacy_mock)

        legacy_result = await call_llm(
            event_profile,
            "deeper progressive house",
        )

    # Identical structured output across both paths.
    assert len(gateway_result.queries) == len(legacy_result.queries) == 2
    for gq, lq in zip(gateway_result.queries, legacy_result.queries):
        assert gq.search_query == lq.search_query
        assert gq.target_bpm == lq.target_bpm
        assert gq.target_key == lq.target_key
        assert gq.target_genre == lq.target_genre
        assert gq.reasoning == lq.reasoning


@pytest.mark.asyncio
async def test_gateway_routes_gemini_connector(db, test_user, event_profile):
    """When the active DJ connector is Gemini, the recommendation engine routes
    through the Gemini adapter and produces structured queries.
    """
    from app.models.llm_connector import LlmConnector

    connector = LlmConnector(
        user_id=test_user.id,
        connector_type="gemini_apikey",
        display_name="Gemini",
        status="active",
        credentials=json.dumps({"api_key": "AIzaSyA1234567890abcdefghijklmnopqrstuv"}),
        model_hint="gemini-2.5-flash",
    )
    db.add(connector)
    db.commit()
    db.refresh(connector)

    with patch(
        "app.services.llm.adapters.gemini_apikey.GeminiApiKeyAdapter.chat",
        new=AsyncMock(return_value=GATEWAY_RESPONSE),
    ):
        result = await call_llm(
            event_profile,
            "deeper progressive house",
            db=db,
            actor=test_user,
        )

    assert len(result.queries) == 2
    assert result.queries[0].search_query == "deadmau5 progressive house"
