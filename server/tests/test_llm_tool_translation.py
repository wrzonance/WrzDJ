"""Tests for canonical ToolSpec <-> per-provider translation + response parsing."""

import pytest

from app.services.llm.base import ToolSpec
from app.services.llm.exceptions import ToolTranslationError
from app.services.llm.tool_translation import (
    parse_anthropic_response,
    parse_openai_response,
    to_anthropic_tools,
    to_openai_tools,
)

TOOL = ToolSpec(
    name="rank_recommendations",
    description="Rank the candidates",
    input_schema={
        "type": "object",
        "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["ids"],
    },
)


class TestOpenAITools:
    def test_returns_none_for_no_tools(self):
        tools, choice = to_openai_tools(None, None)
        assert tools is None
        assert choice is None

    def test_translates_tools(self):
        tools, choice = to_openai_tools([TOOL], None)
        assert tools is not None
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "rank_recommendations"
        assert tools[0]["function"]["parameters"] == TOOL.input_schema
        assert choice is None

    def test_force_tool(self):
        tools, choice = to_openai_tools([TOOL], "rank_recommendations")
        assert choice == {
            "type": "function",
            "function": {"name": "rank_recommendations"},
        }

    def test_force_tool_not_in_list(self):
        with pytest.raises(ToolTranslationError):
            to_openai_tools([TOOL], "does_not_exist")


class TestAnthropicTools:
    def test_returns_none_for_no_tools(self):
        tools, choice = to_anthropic_tools(None, None)
        assert tools is None
        assert choice is None

    def test_translates_tools(self):
        tools, choice = to_anthropic_tools([TOOL], None)
        assert tools is not None
        assert tools[0]["name"] == "rank_recommendations"
        assert tools[0]["input_schema"] == TOOL.input_schema
        assert choice is None

    def test_force_tool(self):
        tools, choice = to_anthropic_tools([TOOL], "rank_recommendations")
        assert choice == {"type": "tool", "name": "rank_recommendations"}


class TestParseOpenAIResponse:
    def test_text_response(self):
        body = {
            "model": "gpt-5-mini",
            "choices": [
                {"finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }
        resp = parse_openai_response(body)
        assert resp.text == "hi"
        assert resp.stop_reason == "end_turn"
        assert resp.tool_calls == []
        assert resp.usage.prompt == 3
        assert resp.usage.completion == 1
        assert resp.model == "gpt-5-mini"

    def test_tool_call(self):
        body = {
            "model": "gpt-5-mini",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "rank_recommendations",
                                    "arguments": '{"ids": ["a", "b"]}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        resp = parse_openai_response(body)
        assert resp.stop_reason == "tool_use"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "rank_recommendations"
        assert resp.tool_calls[0].input == {"ids": ["a", "b"]}
        assert resp.tool_calls[0].id == "call_1"

    def test_malformed_response(self):
        with pytest.raises(ToolTranslationError):
            parse_openai_response({"foo": "bar"})

    def test_tool_arguments_invalid_json(self):
        body = {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "rank",
                                    "arguments": "{not json",
                                },
                            }
                        ]
                    },
                }
            ]
        }
        with pytest.raises(ToolTranslationError):
            parse_openai_response(body)

    def test_finish_reason_length(self):
        body = {"choices": [{"finish_reason": "length", "message": {"content": "..."}}]}
        resp = parse_openai_response(body)
        assert resp.stop_reason == "max_tokens"


class TestParseAnthropicResponse:
    def test_text_response(self):
        # Use dict shape — adapters accept either SDK objects or dicts.
        msg = {
            "model": "claude-haiku",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 2, "output_tokens": 1},
        }
        resp = parse_anthropic_response(msg)
        assert resp.text == "hello"
        assert resp.stop_reason == "end_turn"
        assert resp.usage.prompt == 2
        assert resp.usage.completion == 1

    def test_tool_use(self):
        msg = {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "rank",
                    "input": {"ids": ["x"]},
                }
            ],
        }
        resp = parse_anthropic_response(msg)
        assert resp.stop_reason == "tool_use"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].input == {"ids": ["x"]}

    def test_max_tokens(self):
        msg = {"stop_reason": "max_tokens", "content": []}
        resp = parse_anthropic_response(msg)
        assert resp.stop_reason == "max_tokens"

    def test_anthropic_tool_use_missing_id_name_raises(self):
        """Regression: malformed tool_use without id/name must fail fast.

        Pin per PR #348: previously the parser cast missing values to the
        string "None", producing invalid canonical ToolCall objects.
        """
        msg = {
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "input": {"ids": ["x"]}}],
        }
        with pytest.raises(ToolTranslationError):
            parse_anthropic_response(msg)

    def test_anthropic_tool_use_empty_name_raises(self):
        """Empty name with no id to fall back to must raise, not emit 'None'."""
        msg = {
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "name": "", "input": {}}],
        }
        with pytest.raises(ToolTranslationError):
            parse_anthropic_response(msg)
