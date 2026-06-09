"""Regression: recommendation engine produces canonical output when routed
through the LLM gateway.

The gateway is the sole credential path — the legacy direct-Anthropic env-var
fallback was removed in #343. These tests pin that gateway-dispatched output is
identical to a direct parse of the equivalent provider response, and that
``call_llm`` now requires a ``db`` session.
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


def test_parse_tool_response_propagates_provider_model():
    """The actual provider model from the gateway response must survive parsing,
    so the UI badge reflects the connector that ran (not a hardcoded default)."""
    from app.services.recommendation.llm_client import _parse_tool_response

    resp = ChatResponse(
        text="",
        tool_calls=[
            ToolCall(id="t", name="search_queries", input={"queries": [{"search_query": "x"}]})
        ],
        stop_reason="tool_use",
        model="gpt-5.4-mini",
    )
    result = _parse_tool_response(resp)
    assert result.model == "gpt-5.4-mini"
    assert result.queries[0].search_query == "x"


@pytest.mark.asyncio
async def test_gateway_path_matches_canonical_parse(db, test_user, event_profile):
    """The gateway path yields the same canonical ``LLMSuggestionResult`` as a
    direct parse of the equivalent provider response.

    The legacy direct-Anthropic env-var path was removed in #343 — the connector
    system is the sole credential source. This pins that the gateway-dispatched
    output is identical to what ``_parse_tool_response`` produces for the same
    model output regardless of the (defensive) input shape it receives.
    """
    # Insert a connector for the actor so the gateway has something to resolve.
    from app.models.llm_connector import LlmConnector
    from app.services.recommendation.llm_client import _parse_tool_response

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

    # Canonical parse of the equivalent Anthropic-SDK-shaped response.
    canonical_result = _parse_tool_response(_legacy_anthropic_response())

    # Identical structured output regardless of response shape.
    assert len(gateway_result.queries) == len(canonical_result.queries) == 2
    for gq, cq in zip(gateway_result.queries, canonical_result.queries):
        assert gq.search_query == cq.search_query
        assert gq.target_bpm == cq.target_bpm
        assert gq.target_key == cq.target_key
        assert gq.target_genre == cq.target_genre
        assert gq.reasoning == cq.reasoning


@pytest.mark.asyncio
async def test_call_llm_requires_db(event_profile):
    """The legacy no-``db`` env-var fallback is gone (#343): callers must supply a
    db session so the gateway can resolve a connector."""
    with pytest.raises(ValueError, match="requires a db session"):
        await call_llm(event_profile, "anything")


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
        # Built at runtime so no scanner-matchable "AIza…" literal is committed.
        credentials=json.dumps({"api_key": "AIza" + ("A" * 35)}),
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
