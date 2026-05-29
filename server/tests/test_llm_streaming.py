"""Tests for streaming primitives: ChatResponseChunk + SSE helpers + adapters."""

from __future__ import annotations

import json as _json

import pytest

from app.models.llm_connector import LlmConnector
from app.services.llm.base import (
    ChatRequest,
    ChatResponseChunk,
    LlmAdapter,
    Message,
    TokenUsage,
    ToolCallDelta,
)
from app.services.llm.exceptions import StreamingUnsupported


# ---------------------------------------------------------------------------
# Task 1 — ChatResponseChunk + ToolCallDelta models
# ---------------------------------------------------------------------------
def test_chunk_defaults_are_empty():
    chunk = ChatResponseChunk()
    assert chunk.text_delta == ""
    assert chunk.tool_call_deltas == []
    assert chunk.stop_reason is None
    assert chunk.usage is None
    assert chunk.done is False


def test_chunk_final_carries_stop_reason_and_usage():
    chunk = ChatResponseChunk(
        stop_reason="end_turn",
        usage=TokenUsage(prompt=3, completion=5),
        done=True,
    )
    assert chunk.done is True
    assert chunk.stop_reason == "end_turn"
    assert chunk.usage.completion == 5


def test_tool_call_delta_fragment_shape():
    delta = ToolCallDelta(index=0, id="call_1", name="search", input_json_fragment='{"q":')
    assert delta.index == 0
    assert delta.id == "call_1"
    assert delta.name == "search"
    assert delta.input_json_fragment == '{"q":'


# ---------------------------------------------------------------------------
# Task 2 — default stream() raises StreamingUnsupported
# ---------------------------------------------------------------------------
class _BareAdapter(LlmAdapter):
    connector_type = "bare"

    async def chat(self, request):  # pragma: no cover
        raise NotImplementedError

    async def health_check(self):  # pragma: no cover
        raise NotImplementedError


async def test_default_stream_raises_streaming_unsupported():
    adapter = _BareAdapter(connector=None)
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(StreamingUnsupported):
        async for _ in adapter.stream(req):
            pass


# ---------------------------------------------------------------------------
# Task 3 — OpenAI streaming event parser
# ---------------------------------------------------------------------------
def test_parse_openai_stream_line_text():
    from app.services.llm.streaming import parse_openai_stream_event

    chunk = parse_openai_stream_event(
        {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}
    )
    assert chunk is not None
    assert chunk.text_delta == "Hello"
    assert chunk.tool_call_deltas == []
    assert chunk.done is False


def test_parse_openai_stream_line_tool_call_fragment():
    from app.services.llm.streaming import parse_openai_stream_event

    chunk = parse_openai_stream_event(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "search", "arguments": '{"q":'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
    )
    assert chunk is not None
    assert chunk.text_delta == ""
    assert len(chunk.tool_call_deltas) == 1
    d = chunk.tool_call_deltas[0]
    assert d.index == 0 and d.id == "call_1" and d.name == "search"
    assert d.input_json_fragment == '{"q":'


def test_parse_openai_stream_line_finish():
    from app.services.llm.streaming import parse_openai_stream_event

    chunk = parse_openai_stream_event(
        {
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 11},
        }
    )
    assert chunk is not None
    assert chunk.done is True
    assert chunk.stop_reason == "tool_use"
    assert chunk.usage is not None and chunk.usage.prompt == 7


def test_parse_openai_stream_line_role_only_returns_none():
    from app.services.llm.streaming import parse_openai_stream_event

    chunk = parse_openai_stream_event(
        {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]}
    )
    assert chunk is None


def test_parse_openai_stream_line_unknown_finish_reason_maps_error():
    from app.services.llm.streaming import parse_openai_stream_event

    chunk = parse_openai_stream_event(
        {"choices": [{"delta": {}, "finish_reason": "content_filter"}]}
    )
    assert chunk is not None
    assert chunk.done is True
    assert chunk.stop_reason == "error"


# ---------------------------------------------------------------------------
# Task 4 — httpx OpenAI streaming generator
# ---------------------------------------------------------------------------
class _FakeStreamResponse:
    """Minimal stand-in for an httpx streaming response."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


class _FakeStreamClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        client = self

        class _Ctx:
            async def __aenter__(self_inner):
                return client._response

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


async def test_stream_openai_chat_yields_text_then_final(monkeypatch):
    from app.services.llm.adapters import _httpx_openai

    sse_lines = [
        'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":" there"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":4,"completion_tokens":2}}',
        "data: [DONE]",
    ]
    fake_resp = _FakeStreamResponse(sse_lines)
    monkeypatch.setattr(
        _httpx_openai.httpx, "AsyncClient", lambda *a, **k: _FakeStreamClient(fake_resp)
    )

    req = ChatRequest(messages=[Message(role="user", content="hi")], model="gpt-x")
    chunks = []
    async for c in _httpx_openai.stream_openai_chat(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        request=req,
        fallback_model="gpt-x",
    ):
        chunks.append(c)

    text = "".join(c.text_delta for c in chunks)
    assert text == "Hi there"
    assert chunks[-1].done is True
    assert chunks[-1].stop_reason == "end_turn"
    assert chunks[-1].usage.prompt == 4


async def test_stream_openai_chat_maps_auth_error(monkeypatch):
    from app.services.llm.adapters import _httpx_openai
    from app.services.llm.exceptions import AuthInvalid

    fake_resp = _FakeStreamResponse([], status_code=401)
    monkeypatch.setattr(
        _httpx_openai.httpx, "AsyncClient", lambda *a, **k: _FakeStreamClient(fake_resp)
    )

    req = ChatRequest(messages=[Message(role="user", content="hi")], model="gpt-x")
    with pytest.raises(AuthInvalid):
        async for _ in _httpx_openai.stream_openai_chat(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            request=req,
            fallback_model="gpt-x",
        ):
            pass


# ---------------------------------------------------------------------------
# Task 5 — OpenAI platform + compatible adapter stream()
# ---------------------------------------------------------------------------
async def test_openai_apikey_adapter_stream(monkeypatch):
    from app.services.llm.adapters import openai_apikey

    captured = {}

    async def fake_stream(**kwargs):
        captured.update(kwargs)
        yield ChatResponseChunk(text_delta="ok", done=False)
        yield ChatResponseChunk(stop_reason="end_turn", done=True)

    monkeypatch.setattr(openai_apikey, "stream_openai_chat", fake_stream)

    connector = LlmConnector(
        user_id=1,
        connector_type="openai_apikey",
        display_name="x",
        status="active",
        credentials=_json.dumps({"api_key": "sk-test"}),
        model_hint="gpt-x",
    )
    adapter = openai_apikey.OpenAIApiKeyAdapter(connector)
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    chunks = [c async for c in adapter.stream(req)]
    assert [c.text_delta for c in chunks] == ["ok", ""]
    assert chunks[-1].done is True
    assert captured["max_tokens_field"] == "max_completion_tokens"
    assert captured["api_key"] == "sk-test"


async def test_openai_compatible_adapter_stream(monkeypatch):
    from app.services.llm.adapters import openai_compatible

    async def fake_stream(**kwargs):
        assert kwargs["base_url"] == "http://127.0.0.1:1234/v1"
        yield ChatResponseChunk(text_delta="hey", done=False)
        yield ChatResponseChunk(stop_reason="end_turn", done=True)

    monkeypatch.setattr(openai_compatible, "stream_openai_chat", fake_stream)

    connector = LlmConnector(
        user_id=1,
        connector_type="openai_compatible",
        display_name="local",
        status="active",
        credentials=_json.dumps({"base_url": "http://127.0.0.1:1234/v1"}),
        model_hint="local-model",
    )
    adapter = openai_compatible.OpenAICompatibleAdapter(connector)
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    chunks = [c async for c in adapter.stream(req)]
    assert "".join(c.text_delta for c in chunks) == "hey"
    assert chunks[-1].done is True


# ---------------------------------------------------------------------------
# Task 6 — Anthropic adapter stream()
# ---------------------------------------------------------------------------
class _FakeEvent:
    """Stand-in for an anthropic SDK stream event (attribute access)."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeAnthropicStream:
    def __init__(self, events):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for e in self._events:
            yield e


def _anthropic_text_events():
    return [
        _FakeEvent(type="message_start"),
        _FakeEvent(
            type="content_block_start",
            index=0,
            content_block=_FakeEvent(type="text", text=""),
        ),
        _FakeEvent(
            type="content_block_delta",
            index=0,
            delta=_FakeEvent(type="text_delta", text="Hel"),
        ),
        _FakeEvent(
            type="content_block_delta",
            index=0,
            delta=_FakeEvent(type="text_delta", text="lo"),
        ),
        _FakeEvent(type="content_block_stop", index=0),
        _FakeEvent(
            type="message_delta",
            delta=_FakeEvent(stop_reason="end_turn"),
            usage=_FakeEvent(output_tokens=5),
        ),
        _FakeEvent(type="message_stop"),
    ]


def _anthropic_tool_events():
    return [
        _FakeEvent(type="message_start"),
        _FakeEvent(
            type="content_block_start",
            index=0,
            content_block=_FakeEvent(type="tool_use", id="toolu_1", name="search"),
        ),
        _FakeEvent(
            type="content_block_delta",
            index=0,
            delta=_FakeEvent(type="input_json_delta", partial_json='{"q":'),
        ),
        _FakeEvent(
            type="content_block_delta",
            index=0,
            delta=_FakeEvent(type="input_json_delta", partial_json='"house"}'),
        ),
        _FakeEvent(type="content_block_stop", index=0),
        _FakeEvent(
            type="message_delta",
            delta=_FakeEvent(stop_reason="tool_use"),
            usage=_FakeEvent(output_tokens=9),
        ),
        _FakeEvent(type="message_stop"),
    ]


def _patch_fake_anthropic(monkeypatch, events):
    from app.services.llm.adapters import anthropic_apikey

    class _FakeMessages:
        def stream(self, **kwargs):
            return _FakeAnthropicStream(events)

    class _FakeClient:
        def __init__(self, *a, **k):
            self.messages = _FakeMessages()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(anthropic_apikey, "AsyncAnthropic", _FakeClient)


def _anthropic_connector():
    return LlmConnector(
        user_id=1,
        connector_type="anthropic_apikey",
        display_name="claude",
        status="active",
        credentials=_json.dumps({"api_key": "sk-ant-test"}),
        model_hint="claude-x",
    )


async def test_anthropic_adapter_stream_text(monkeypatch):
    from app.services.llm.adapters import anthropic_apikey

    _patch_fake_anthropic(monkeypatch, _anthropic_text_events())
    adapter = anthropic_apikey.AnthropicApiKeyAdapter(_anthropic_connector())
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    chunks = [c async for c in adapter.stream(req)]
    assert "".join(c.text_delta for c in chunks) == "Hello"
    assert chunks[-1].done is True
    assert chunks[-1].stop_reason == "end_turn"
    assert chunks[-1].usage.completion == 5


async def test_anthropic_adapter_stream_tool_use(monkeypatch):
    from app.services.llm.adapters import anthropic_apikey

    _patch_fake_anthropic(monkeypatch, _anthropic_tool_events())
    adapter = anthropic_apikey.AnthropicApiKeyAdapter(_anthropic_connector())
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    chunks = [c async for c in adapter.stream(req)]

    frags = [d for c in chunks for d in c.tool_call_deltas]
    assert frags[0].id == "toolu_1" and frags[0].name == "search"
    joined = "".join(d.input_json_fragment for d in frags)
    assert _json.loads(joined) == {"q": "house"}
    assert chunks[-1].done is True
    assert chunks[-1].stop_reason == "tool_use"
