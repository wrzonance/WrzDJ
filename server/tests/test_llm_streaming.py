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


def test_parse_openai_stream_tolerates_non_numeric_tool_index():
    """A null/non-numeric tool-call ``index`` must not abort the stream (#379)."""
    from app.services.llm.streaming import parse_openai_stream_event

    chunk = parse_openai_stream_event(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": None,
                                "id": "call_1",
                                "function": {"name": "search", "arguments": "{}"},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
    )
    assert chunk is not None
    assert chunk.tool_call_deltas[0].index == 0  # fell back to default, no raise


def test_parse_openai_stream_tolerates_non_numeric_usage():
    """Malformed/null token counts must not abort the terminal chunk (#379)."""
    from app.services.llm.streaming import parse_openai_stream_event

    chunk = parse_openai_stream_event(
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": None, "completion_tokens": "oops"},
        }
    )
    assert chunk is not None
    assert chunk.done is True
    # Non-numeric counts coerce to 0 rather than raising mid-stream; the terminal
    # chunk is still delivered with a (zeroed) usage block.
    assert chunk.usage is not None
    assert chunk.usage.prompt == 0
    assert chunk.usage.completion == 0


def test_parse_openai_stream_usage_only_terminal_event_preserved():
    """A usage-only terminal event (empty ``choices``) must not be dropped (#354).

    With ``stream_options.include_usage`` OpenAI emits a final frame carrying only
    ``usage`` and ``choices: []`` — no delta, no ``finish_reason``. Previously the
    parser returned ``None`` for it (``done`` is driven solely by ``finish_reason``)
    so token accounting was silently lost. It must now yield a usage-bearing chunk.
    """
    from app.services.llm.streaming import parse_openai_stream_event

    chunk = parse_openai_stream_event(
        {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}
    )
    assert chunk is not None
    assert chunk.done is False
    assert chunk.text_delta == ""
    assert chunk.tool_call_deltas == []
    assert chunk.usage is not None
    assert chunk.usage.prompt == 9
    assert chunk.usage.completion == 4


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

    # SSE events are blank-line delimited (``aiter_lines`` yields "" for a blank
    # line). Real OpenAI frames each ``data:`` line that way.
    sse_lines = [
        'data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}',
        "",
        'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}',
        "",
        'data: {"choices":[{"delta":{"content":" there"},"finish_reason":null}]}',
        "",
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":4,"completion_tokens":2}}',
        "",
        "data: [DONE]",
        "",
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


async def test_stream_openai_chat_malformed_data_raises(monkeypatch):
    """A malformed ``data:`` frame surfaces a typed error, not a silent truncation (#379)."""
    from app.services.llm.adapters import _httpx_openai
    from app.services.llm.exceptions import ToolTranslationError

    sse_lines = [
        'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}',
        "",
        "data: {not valid json",
        "",
    ]
    fake_resp = _FakeStreamResponse(sse_lines)
    monkeypatch.setattr(
        _httpx_openai.httpx, "AsyncClient", lambda *a, **k: _FakeStreamClient(fake_resp)
    )

    req = ChatRequest(messages=[Message(role="user", content="hi")], model="gpt-x")
    collected = []
    with pytest.raises(ToolTranslationError):
        async for c in _httpx_openai.stream_openai_chat(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            request=req,
            fallback_model="gpt-x",
        ):
            collected.append(c)
    # The valid leading chunk was still delivered before the fault surfaced.
    assert collected and collected[0].text_delta == "Hi"


async def test_stream_openai_chat_reassembles_multiline_data_event(monkeypatch):
    """One SSE event split across multiple ``data:`` lines is reassembled (#354).

    SSE permits a single event to span several ``data:`` lines (joined on
    newlines); an OpenAI-compatible server may emit JSON that way. Decoding each
    line on its own would raise on the first fragment and truncate the stream, so
    the parser must buffer the whole event before JSON-decoding it.
    """
    from app.services.llm.adapters import _httpx_openai

    sse_lines = [
        # A single JSON object wrapped across two data lines — valid only once
        # the two payloads are rejoined with a newline.
        'data: {"choices":[{"delta":{"content":"Hi there"},',
        'data: "finish_reason":null}]}',
        "",
        "data: [DONE]",
        "",
    ]
    fake_resp = _FakeStreamResponse(sse_lines)
    monkeypatch.setattr(
        _httpx_openai.httpx, "AsyncClient", lambda *a, **k: _FakeStreamClient(fake_resp)
    )

    req = ChatRequest(messages=[Message(role="user", content="hi")], model="gpt-x")
    chunks = [
        c
        async for c in _httpx_openai.stream_openai_chat(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            request=req,
            fallback_model="gpt-x",
        )
    ]
    assert "".join(c.text_delta for c in chunks) == "Hi there"


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


@pytest.mark.parametrize("native_stop", ["refusal", "pause_turn", "something_new"])
async def test_anthropic_stream_unmodelled_stop_matches_chat(monkeypatch, native_stop):
    """Stream + chat must canonicalise unmodelled stop_reasons identically (#379).

    Anthropic can emit ``pause_turn`` / ``refusal`` which we don't model
    canonically; both paths must map them to ``"error"`` (not ``"end_turn"``).
    """
    from app.services.llm.adapters import anthropic_apikey
    from app.services.llm.tool_translation import normalise_anthropic_stop_reason

    events = [
        _FakeEvent(type="message_start"),
        _FakeEvent(
            type="content_block_start", index=0, content_block=_FakeEvent(type="text", text="")
        ),
        _FakeEvent(
            type="content_block_delta", index=0, delta=_FakeEvent(type="text_delta", text="x")
        ),
        _FakeEvent(
            type="message_delta",
            delta=_FakeEvent(stop_reason=native_stop),
            usage=_FakeEvent(output_tokens=1),
        ),
        _FakeEvent(type="message_stop"),
    ]
    _patch_fake_anthropic(monkeypatch, events)
    adapter = anthropic_apikey.AnthropicApiKeyAdapter(_anthropic_connector())
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    chunks = [c async for c in adapter.stream(req)]

    assert chunks[-1].done is True
    # The streamed canonical stop_reason equals what the buffered path would give.
    assert chunks[-1].stop_reason == normalise_anthropic_stop_reason(native_stop)
    assert chunks[-1].stop_reason == "error"


def test_translate_anthropic_event_handles_plain_dicts():
    """Dict-backed events (not only SDK objects) must yield deltas (#354).

    ``_translate_anthropic_event``'s docstring promises dict support, but the
    original implementation read fields via ``getattr`` only — so dict events
    silently produced empty chunks. Each branch must honour dict access.
    """
    from app.services.llm.adapters.anthropic_apikey import _translate_anthropic_event

    # tool_use block start
    chunk, saw_tool, stop, out_tokens = _translate_anthropic_event(
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "search"},
        }
    )
    assert saw_tool is True
    assert chunk is not None
    assert chunk.tool_call_deltas[0].id == "toolu_1"
    assert chunk.tool_call_deltas[0].name == "search"

    # text delta
    chunk, _saw, _stop, _ot = _translate_anthropic_event(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        }
    )
    assert chunk is not None
    assert chunk.text_delta == "Hello"

    # input_json (tool argument) delta
    chunk, _saw, _stop, _ot = _translate_anthropic_event(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":'},
        }
    )
    assert chunk is not None
    assert chunk.tool_call_deltas[0].input_json_fragment == '{"q":'

    # message_delta carries stop_reason + usage
    chunk, _saw, stop, out_tokens = _translate_anthropic_event(
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 7},
        }
    )
    assert chunk is None
    assert stop == "end_turn"
    assert out_tokens == 7
