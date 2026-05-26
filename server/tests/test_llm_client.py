"""Tests for the LLM client module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.base import ChatResponse, ToolCall
from app.services.recommendation.llm_client import (
    SEARCH_QUERIES_TOOL,
    SYSTEM_PROMPT,
    _parse_tool_response,
    build_user_prompt,
    call_llm,
)
from app.services.recommendation.scorer import EventProfile, TrackProfile


class TestBuildUserPrompt:
    def test_empty_profile(self):
        profile = EventProfile(track_count=0)
        result = build_user_prompt(profile, "chill vibes")
        assert "DJ's request: chill vibes" in result
        assert "No tracks accepted yet" in result

    def test_full_profile(self):
        profile = EventProfile(
            avg_bpm=128.0,
            bpm_range=(120.0, 136.0),
            dominant_keys=["8A", "9A"],
            dominant_genres=["Tech House", "House"],
            track_count=10,
        )
        result = build_user_prompt(profile, "something darker")
        assert "DJ's request: something darker" in result
        assert "Tracks analyzed: 10" in result
        assert "Average BPM: 128" in result
        assert "BPM range: 120-136" in result
        assert "8A, 9A" in result
        assert "Tech House, House" in result

    def test_partial_profile_no_bpm(self):
        profile = EventProfile(
            dominant_genres=["Hip Hop"],
            track_count=3,
        )
        result = build_user_prompt(profile, "90s classics")
        assert "Tracks analyzed: 3" in result
        assert "Hip Hop" in result
        assert "Average BPM" not in result
        assert "BPM range" not in result

    def test_with_track_list(self):
        profile = EventProfile(avg_bpm=128.0, track_count=2)
        tracks = [
            TrackProfile(
                title="Strobe",
                artist="deadmau5",
                bpm=128.0,
                key="8A",
                genre="Progressive House",
            ),
            TrackProfile(title="Levels", artist="Avicii", bpm=126.0),
        ]
        result = build_user_prompt(profile, "more like these", tracks=tracks)
        assert "Tracks in the set:" in result
        assert "deadmau5 — Strobe (128 BPM, 8A, Progressive House)" in result
        assert "Avicii — Levels (126 BPM)" in result

    def test_track_list_capped_at_30(self):
        profile = EventProfile(track_count=40)
        tracks = [TrackProfile(title=f"Track {i}", artist=f"Artist {i}") for i in range(40)]
        result = build_user_prompt(profile, "test", tracks=tracks)
        assert "Artist 29 — Track 29" in result
        assert "Artist 30 — Track 30" not in result

    def test_no_tracks_omits_section(self):
        profile = EventProfile(track_count=0)
        result = build_user_prompt(profile, "test", tracks=None)
        assert "Tracks in the set:" not in result
        result2 = build_user_prompt(profile, "test", tracks=[])
        assert "Tracks in the set:" not in result2


class TestParseToolResponse:
    def test_valid_tool_use(self):
        response = MagicMock()
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_queries"
        tool_block.input = {
            "queries": [
                {
                    "search_query": "deadmau5 progressive house",
                    "target_bpm": 128.0,
                    "target_key": "8A",
                    "target_genre": "Progressive House",
                    "reasoning": "Matches dark progressive style",
                },
                {
                    "search_query": "eric prydz",
                    "reasoning": "Similar artist",
                },
            ]
        }
        response.content = [tool_block]

        result = _parse_tool_response(response)
        assert len(result.queries) == 2
        assert result.queries[0].search_query == "deadmau5 progressive house"
        assert result.queries[0].target_bpm == 128.0
        assert result.queries[0].target_key == "8A"
        assert result.queries[0].target_genre == "Progressive House"
        assert result.queries[1].search_query == "eric prydz"
        assert result.queries[1].target_bpm is None
        assert result.queries[1].target_key is None

    def test_empty_queries(self):
        response = MagicMock()
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_queries"
        tool_block.input = {"queries": []}
        response.content = [tool_block]

        result = _parse_tool_response(response)
        assert len(result.queries) == 0

    def test_text_only_fallback(self):
        response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I cannot generate queries."
        response.content = [text_block]

        result = _parse_tool_response(response)
        assert len(result.queries) == 0
        assert "I cannot generate queries" in result.raw_response

    def test_mixed_content_blocks(self):
        response = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Here are my suggestions: "

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_queries"
        tool_block.input = {
            "queries": [{"search_query": "avicii levels", "reasoning": "Requested song"}]
        }
        response.content = [text_block, tool_block]

        result = _parse_tool_response(response)
        assert len(result.queries) == 1
        assert result.queries[0].search_query == "avicii levels"
        assert "Here are my suggestions" in result.raw_response


class TestCallLLM:
    """``call_llm`` always routes through the LLM Gateway.

    The legacy direct-Anthropic env-var fallback was removed in #343 — every
    production caller supplies ``db`` + ``actor`` and the connector system is
    the sole source of credentials. These tests patch ``Gateway.dispatch``.
    """

    @pytest.mark.asyncio
    @patch("app.services.recommendation.llm_client.Gateway")
    async def test_dispatches_via_gateway(self, mock_gateway):
        response = ChatResponse(
            tool_calls=[
                ToolCall(
                    id="t1",
                    name="search_queries",
                    input={
                        "queries": [
                            {"search_query": "chill house", "reasoning": "DJ wants chill vibes"}
                        ]
                    },
                )
            ],
            stop_reason="tool_use",
            model="claude-haiku-4-5-20251001",
        )
        mock_gateway.dispatch = AsyncMock(return_value=response)

        db = MagicMock()
        actor = MagicMock()
        profile = EventProfile(avg_bpm=120.0, dominant_genres=["House"], track_count=5)

        result = await call_llm(profile, "chill vibes", db=db, actor=actor)

        assert len(result.queries) == 1
        assert result.queries[0].search_query == "chill house"
        assert result.model == "claude-haiku-4-5-20251001"

        mock_gateway.dispatch.assert_awaited_once()
        # Positional args: (db, actor, chat_request); keyword: purpose.
        args, kwargs = mock_gateway.dispatch.call_args
        assert args[0] is db
        assert args[1] is actor
        chat_request = args[2]
        assert chat_request.force_tool == "search_queries"
        assert chat_request.max_tokens == 1024
        assert kwargs["purpose"] == "recommendation"

    @pytest.mark.asyncio
    @patch("app.services.recommendation.llm_client.Gateway")
    async def test_trims_to_max_queries(self, mock_gateway):
        response = ChatResponse(
            tool_calls=[
                ToolCall(
                    id="t1",
                    name="search_queries",
                    input={
                        "queries": [
                            {"search_query": f"query {i}", "reasoning": f"reason {i}"}
                            for i in range(5)
                        ]
                    },
                )
            ],
            stop_reason="tool_use",
        )
        mock_gateway.dispatch = AsyncMock(return_value=response)

        profile = EventProfile(track_count=0)
        result = await call_llm(profile, "test", max_queries=2, db=MagicMock(), actor=MagicMock())

        assert len(result.queries) == 2
        assert result.queries[0].search_query == "query 0"
        assert result.queries[1].search_query == "query 1"


class TestSystemPrompt:
    def test_contains_key_concepts(self):
        assert "BPM" in SYSTEM_PROMPT
        assert "Camelot" in SYSTEM_PROMPT
        assert "genre" in SYSTEM_PROMPT.lower()
        assert "DJ" in SYSTEM_PROMPT

    def test_is_nonempty_string(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 100


class TestToolDefinition:
    def test_has_required_fields(self):
        assert SEARCH_QUERIES_TOOL["name"] == "search_queries"
        assert "input_schema" in SEARCH_QUERIES_TOOL
        schema = SEARCH_QUERIES_TOOL["input_schema"]
        assert schema["type"] == "object"
        assert "queries" in schema["properties"]

    def test_query_schema_structure(self):
        query_schema = SEARCH_QUERIES_TOOL["input_schema"]["properties"]["queries"]
        assert query_schema["type"] == "array"
        item_props = query_schema["items"]["properties"]
        assert "search_query" in item_props
        assert "target_bpm" in item_props
        assert "target_key" in item_props
        assert "target_genre" in item_props
        assert "reasoning" in item_props
        assert "search_query" in query_schema["items"]["required"]
        assert "reasoning" in query_schema["items"]["required"]
