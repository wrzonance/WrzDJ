# LLM Gateway Streaming Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add provider-agnostic streaming (`Gateway.stream`) to the LLM Gateway with native SSE for OpenAI, Anthropic, and OpenAI-compatible adapters, an authenticated SSE backend endpoint, and a minimal frontend consumer — closing GitHub issue #335.

**Architecture:** A new `ChatResponseChunk` canonical model carries incremental text, partial tool-call fragments, and (on the final chunk) `stop_reason` + `usage`. The `LlmAdapter` ABC gains an `async def stream(self, request) -> AsyncIterator[ChatResponseChunk]` with a default that raises `StreamingUnsupported`. OpenAI-wire adapters (platform + compatible) parse SSE `data:` lines with incremental tool-call JSON assembly; the Anthropic adapter consumes the SDK's typed event stream (content_block_delta / input_json_delta). `Gateway.stream` mirrors `dispatch`'s connector resolution and writes a single counts-only `llm_call_log` row (plus auth/audit rows) when the stream completes or errors. A new authenticated `POST /api/llm/connectors/{id}/stream-test` endpoint emits `text/event-stream`; client disconnect cancels the upstream request via async generator cleanup. The frontend gets an `apiClient.streamConnectorTest()` consumer using `fetch` + `ReadableStream` (EventSource cannot send the Bearer header).

**Tech Stack:** Python / FastAPI / `sse_starlette` (already a dep) / `httpx` async streaming / `anthropic` SDK `messages.stream()` / pytest-asyncio. Frontend: Next.js / TypeScript / `fetch` streaming.

---

## File Structure

- **Create** `server/app/services/llm/streaming.py` — `ChatResponseChunk` model + `StreamingUnsupported` exception + shared SSE-line helpers (`iter_sse_data_lines`, OpenAI partial tool-call accumulator). One responsibility: streaming primitives shared by adapters.
- **Modify** `server/app/services/llm/base.py` — add `stream()` to the `LlmAdapter` ABC with a non-abstract default that raises `StreamingUnsupported`; re-export `ChatResponseChunk`.
- **Modify** `server/app/services/llm/exceptions.py` — add `StreamingUnsupported(LlmError)`.
- **Modify** `server/app/services/llm/adapters/_httpx_openai.py` — add `stream_openai_chat(...)` async generator.
- **Modify** `server/app/services/llm/adapters/openai_apikey.py` — implement `stream()`.
- **Modify** `server/app/services/llm/adapters/openai_compatible.py` — implement `stream()`.
- **Modify** `server/app/services/llm/adapters/anthropic_apikey.py` — implement `stream()`.
- **Modify** `server/app/services/llm/gateway.py` — add `Gateway.stream(...)` + `_attempt_stream(...)` helper (additive, separate functions — no edits to existing `dispatch`/`_attempt` bodies, to minimize merge conflicts with siblings #337/#339).
- **Modify** `server/app/api/llm.py` — add `POST /connectors/{id}/stream-test` SSE endpoint.
- **Modify** `dashboard/lib/api.ts` — add `streamConnectorTest(id, onChunk)` consumer + a `StreamChunk` type.
- **Modify** `dashboard/app/admin/ai/page.tsx` — wire a minimal "stream test" affordance OR document scope as plumbing-only (decision recorded in Task 11).
- **Create** `server/tests/test_llm_streaming.py` — chunk model + adapter stream parsing (OpenAI text, OpenAI tool-call fragments, Anthropic deltas, compatible, unsupported default).
- **Create** `server/tests/test_llm_gateway_stream.py` — gateway resolution + logging + cancellation propagation.
- **Create** `server/tests/test_llm_stream_endpoint.py` — SSE endpoint auth + content-type + body shape.

---

## Task 1: `ChatResponseChunk` model + `StreamingUnsupported` exception

**Files:**
- Create: `server/app/services/llm/streaming.py`
- Modify: `server/app/services/llm/exceptions.py`
- Modify: `server/app/services/llm/base.py`
- Test: `server/tests/test_llm_streaming.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_llm_streaming.py
"""Tests for streaming primitives: ChatResponseChunk + SSE helpers."""

from __future__ import annotations

from app.services.llm.base import ChatResponseChunk, LlmAdapter
from app.services.llm.exceptions import StreamingUnsupported


def test_chunk_defaults_are_empty():
    chunk = ChatResponseChunk()
    assert chunk.text_delta == ""
    assert chunk.tool_call_deltas == []
    assert chunk.stop_reason is None
    assert chunk.usage is None
    assert chunk.done is False


def test_chunk_final_carries_stop_reason_and_usage():
    from app.services.llm.base import TokenUsage

    chunk = ChatResponseChunk(
        stop_reason="end_turn",
        usage=TokenUsage(prompt=3, completion=5),
        done=True,
    )
    assert chunk.done is True
    assert chunk.stop_reason == "end_turn"
    assert chunk.usage.completion == 5


def test_tool_call_delta_fragment_shape():
    from app.services.llm.base import ToolCallDelta

    delta = ToolCallDelta(index=0, id="call_1", name="search", input_json_fragment='{"q":')
    assert delta.index == 0
    assert delta.id == "call_1"
    assert delta.name == "search"
    assert delta.input_json_fragment == '{"q":'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py -q`
Expected: FAIL with `ImportError: cannot import name 'ChatResponseChunk'`

- [ ] **Step 3: Add `StreamingUnsupported` to exceptions**

In `server/app/services/llm/exceptions.py`, append:

```python


class StreamingUnsupported(LlmError):
    """The resolved adapter does not implement provider-native streaming."""
```

- [ ] **Step 4: Create `streaming.py` with chunk-side helpers (model lives in base.py)**

The chunk + delta models live in `base.py` (Task adds them there) so they sit alongside `ChatResponse`. `streaming.py` holds the SSE-line helpers only — created in Task 4. For this task, only add the models to `base.py`.

In `server/app/services/llm/base.py`, after `ChatResponse`, add:

```python
class ToolCallDelta(BaseModel):
    """A fragment of a streamed tool call.

    Providers emit tool-call arguments incrementally. ``index`` groups fragments
    belonging to the same call (OpenAI sends an array index; Anthropic uses the
    content-block index). ``id`` / ``name`` arrive once at the start of a call;
    ``input_json_fragment`` carries the raw, possibly-partial argument JSON text.
    Consumers concatenate fragments per ``index`` and JSON-parse the result when
    the stream completes.
    """

    index: int
    id: str | None = None
    name: str | None = None
    input_json_fragment: str = ""


class ChatResponseChunk(BaseModel):
    """One incremental chunk of a streamed chat response.

    Non-final chunks carry ``text_delta`` and/or ``tool_call_deltas``. The final
    chunk sets ``done=True`` and carries the canonical ``stop_reason`` plus
    ``usage`` (when the provider reports it). ``stop_reason``/``usage`` may be
    ``None`` on every non-final chunk.
    """

    text_delta: str = ""
    tool_call_deltas: list[ToolCallDelta] = Field(default_factory=list)
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "error"] | None = None
    usage: TokenUsage | None = None
    done: bool = False
```

- [ ] **Step 5: Add `stream()` default to the `LlmAdapter` ABC**

In `server/app/services/llm/base.py`, add these imports at the top (merge with existing):

```python
from collections.abc import AsyncIterator
```

Then inside `class LlmAdapter`, after `health_check`, add:

```python
    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatResponseChunk]:
        """Stream a chat response as incremental chunks.

        Default raises :class:`StreamingUnsupported`. Adapters that support
        provider-native streaming override this. The body is unreachable but
        present so the method is an async generator for type-checkers.
        """
        from app.services.llm.exceptions import StreamingUnsupported

        raise StreamingUnsupported(
            f"connector_type={self.connector_type!r} does not support streaming"
        )
        yield  # pragma: no cover  (makes this an async generator)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py -q`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add server/app/services/llm/base.py server/app/services/llm/exceptions.py server/tests/test_llm_streaming.py
git commit -m "feat(llm): add ChatResponseChunk + streaming ABC default"
```

---

## Task 2: Default `stream()` raises `StreamingUnsupported`

**Files:**
- Test: `server/tests/test_llm_streaming.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_llm_streaming.py`:

```python
import pytest

from app.services.llm.base import ChatRequest, Message


class _BareAdapter(LlmAdapter):
    connector_type = "bare"

    async def chat(self, request):  # pragma: no cover
        raise NotImplementedError

    async def health_check(self):  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_default_stream_raises_streaming_unsupported():
    adapter = _BareAdapter(connector=None)
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(StreamingUnsupported):
        async for _ in adapter.stream(req):
            pass
```

- [ ] **Step 2: Run test to verify it passes (default already implemented in Task 1)**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py::test_default_stream_raises_streaming_unsupported -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_llm_streaming.py
git commit -m "test(llm): default adapter stream raises StreamingUnsupported"
```

---

## Task 3: OpenAI partial tool-call accumulator helper

**Files:**
- Create: `server/app/services/llm/streaming.py`
- Test: `server/tests/test_llm_streaming.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_llm_streaming.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py -k parse_openai_stream -q`
Expected: FAIL with `ModuleNotFoundError`/`ImportError` for `streaming.parse_openai_stream_event`

- [ ] **Step 3: Create `streaming.py` helpers**

```python
# server/app/services/llm/streaming.py
"""Shared streaming primitives for LLM adapters.

Holds SSE-line parsing helpers reused by the OpenAI-wire adapters. The chunk /
delta models themselves live in ``base.py`` alongside ``ChatResponse``.
"""

from __future__ import annotations

from app.services.llm.base import ChatResponseChunk, ToolCallDelta, TokenUsage
from app.services.llm.tool_translation import _normalise_finish_reason  # noqa: PLC2701

# OpenAI streaming finish_reason → canonical, reusing the non-stream mapping.
_FINISH_REASON_OPENAI = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
}


def parse_openai_stream_event(payload: dict) -> ChatResponseChunk | None:
    """Translate one parsed OpenAI streaming JSON object into a chunk.

    Returns ``None`` for payloads carrying no usable signal (e.g. the initial
    role-only delta). The final event sets ``done=True`` with the mapped
    ``stop_reason`` and (when present) token usage.
    """
    choices = payload.get("choices") or []
    choice = choices[0] if choices else {}
    delta = choice.get("delta") or {}

    text_delta = delta.get("content") or ""

    tool_call_deltas: list[ToolCallDelta] = []
    for tc in delta.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        tool_call_deltas.append(
            ToolCallDelta(
                index=int(tc.get("index", 0)),
                id=tc.get("id"),
                name=(fn.get("name") if isinstance(fn, dict) else None),
                input_json_fragment=(
                    (fn.get("arguments") or "") if isinstance(fn, dict) else ""
                ),
            )
        )

    finish_reason = choice.get("finish_reason")
    usage_payload = payload.get("usage") or {}

    done = finish_reason is not None
    stop_reason = None
    usage = None
    if done:
        stop_reason = _normalise_finish_reason(finish_reason, _FINISH_REASON_OPENAI)
        if usage_payload:
            usage = TokenUsage(
                prompt=int(usage_payload.get("prompt_tokens", 0)),
                completion=int(usage_payload.get("completion_tokens", 0)),
            )

    if not text_delta and not tool_call_deltas and not done:
        return None

    return ChatResponseChunk(
        text_delta=text_delta,
        tool_call_deltas=tool_call_deltas,
        stop_reason=stop_reason,
        usage=usage,
        done=done,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py -k parse_openai_stream -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/streaming.py server/tests/test_llm_streaming.py
git commit -m "feat(llm): OpenAI streaming event → ChatResponseChunk parser"
```

---

## Task 4: `stream_openai_chat` async generator (httpx)

**Files:**
- Modify: `server/app/services/llm/adapters/_httpx_openai.py`
- Test: `server/tests/test_llm_streaming.py`

- [ ] **Step 1: Write the failing test (mock httpx streaming response)**

Append to `server/tests/test_llm_streaming.py`:

```python
class _FakeStreamResponse:
    """Minimal stand-in for httpx streaming response."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code
        self.headers = {}

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


@pytest.mark.asyncio
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py::test_stream_openai_chat_yields_text_then_final -q`
Expected: FAIL — `stream_openai_chat` not defined

- [ ] **Step 3: Implement `stream_openai_chat` in `_httpx_openai.py`**

Add imports near the top of `server/app/services/llm/adapters/_httpx_openai.py`:

```python
from collections.abc import AsyncIterator

from app.services.llm.base import ChatResponseChunk
from app.services.llm.exceptions import AuthInvalid, QuotaExceeded, RateLimited
from app.services.llm.streaming import parse_openai_stream_event
```

(Merge with the existing import block; `ProviderUnavailable` / `ToolTranslationError` are already imported.)

Add this function after `call_openai_chat`:

```python
def _map_stream_status(status_code: int) -> None:
    """Raise the canonical typed error for a non-2xx streaming status."""
    if status_code in (401, 403):
        raise AuthInvalid(f"Auth failed (HTTP {status_code})")
    if status_code == 402:
        raise QuotaExceeded("Quota or billing failure (HTTP 402)")
    if status_code == 429:
        raise RateLimited("Rate limited (HTTP 429)")
    if 500 <= status_code < 600:
        raise ProviderUnavailable(f"Upstream error (HTTP {status_code})")
    raise ToolTranslationError(f"Upstream rejected request (HTTP {status_code})")


async def stream_openai_chat(
    *,
    base_url: str,
    api_key: str | None,
    request: ChatRequest,
    fallback_model: str | None,
    extra_headers: dict | None = None,
    max_tokens_field: str = "max_tokens",
) -> AsyncIterator[ChatResponseChunk]:
    """Issue a streaming Chat Completions request, yielding canonical chunks.

    Cancellation: if the consumer stops iterating (e.g. SSE client disconnect),
    the ``async with client.stream(...)`` context exits and httpx closes the
    upstream connection, cancelling the provider request. Errors are mapped to
    canonical typed exceptions before the first chunk; mid-stream network drops
    surface as ``ProviderUnavailable``.
    """
    model = request.model or fallback_model
    if not model:
        raise ToolTranslationError(
            "model is required (set ChatRequest.model or LlmConnector.model_hint)"
        )

    endpoint = _build_chat_endpoint(base_url)
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"  # nosec B106
    if extra_headers:
        headers.update(extra_headers)

    timeout = request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    timeout = min(max(timeout, 1.0), MAX_TIMEOUT_SECONDS)

    payload = _build_payload(request, model, max_tokens_field=max_tokens_field)
    payload["stream"] = True
    # Ask OpenAI to include usage in the terminal stream event.
    payload["stream_options"] = {"include_usage": True}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", endpoint, json=payload, headers=headers
            ) as resp:
                if resp.status_code >= 300:
                    # Drain the (small) error body so the connection releases.
                    await resp.aread()
                    _map_stream_status(resp.status_code)
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        # Tolerate keepalive/comment lines.
                        continue
                    chunk = parse_openai_stream_event(obj)
                    if chunk is not None:
                        yield chunk
    except httpx.TimeoutException as exc:
        raise ProviderUnavailable("Upstream timeout") from exc
    except httpx.HTTPError as exc:
        raise ProviderUnavailable("Upstream network error") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py::test_stream_openai_chat_yields_text_then_final -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/adapters/_httpx_openai.py server/tests/test_llm_streaming.py
git commit -m "feat(llm): httpx OpenAI-wire streaming generator"
```

---

## Task 5: OpenAI Platform + OpenAI-compatible adapter `stream()`

**Files:**
- Modify: `server/app/services/llm/adapters/openai_apikey.py`
- Modify: `server/app/services/llm/adapters/openai_compatible.py`
- Test: `server/tests/test_llm_streaming.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_llm_streaming.py`:

```python
@pytest.mark.asyncio
async def test_openai_apikey_adapter_stream(monkeypatch):
    import json as _json

    from app.models.llm_connector import LlmConnector
    from app.services.llm.adapters import openai_apikey
    from app.services.llm.base import ChatResponseChunk

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py::test_openai_apikey_adapter_stream -q`
Expected: FAIL — adapter `stream` falls through to default `StreamingUnsupported`

- [ ] **Step 3: Implement `stream()` in `openai_apikey.py`**

Add to imports:

```python
from collections.abc import AsyncIterator

from app.services.llm.adapters._httpx_openai import (
    build_healthcheck_request,
    call_openai_chat,
    stream_openai_chat,
)
from app.services.llm.base import ChatResponseChunk
```

(Merge with the existing `_httpx_openai` import — add `stream_openai_chat`.)

Add the method to `OpenAIApiKeyAdapter` (after `health_check`):

```python
    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatResponseChunk]:
        api_key = self._extract_api_key()
        async for chunk in stream_openai_chat(
            base_url=OPENAI_BASE_URL,
            api_key=api_key,
            request=request,
            fallback_model=self.connector.model_hint or DEFAULT_MODEL,
            max_tokens_field=_MAX_TOKENS_FIELD,
        ):
            yield chunk
```

- [ ] **Step 4: Implement `stream()` in `openai_compatible.py`**

Add to imports:

```python
from collections.abc import AsyncIterator

from app.services.llm.adapters._httpx_openai import (
    build_healthcheck_request,
    call_openai_chat,
    stream_openai_chat,
)
from app.services.llm.base import ChatResponseChunk
```

Add the method to `OpenAICompatibleAdapter` (after `health_check`):

```python
    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatResponseChunk]:
        base_url, bearer = self._extract_credentials()
        async for chunk in stream_openai_chat(
            base_url=base_url,
            api_key=bearer,
            request=request,
            fallback_model=self.connector.model_hint or DEFAULT_MODEL,
        ):
            yield chunk
```

- [ ] **Step 5: Add a compatible-adapter stream test**

Append to `server/tests/test_llm_streaming.py`:

```python
@pytest.mark.asyncio
async def test_openai_compatible_adapter_stream(monkeypatch):
    import json as _json

    from app.models.llm_connector import LlmConnector
    from app.services.llm.adapters import openai_compatible
    from app.services.llm.base import ChatResponseChunk

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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py -k "openai_apikey_adapter_stream or openai_compatible_adapter_stream" -q`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add server/app/services/llm/adapters/openai_apikey.py server/app/services/llm/adapters/openai_compatible.py server/tests/test_llm_streaming.py
git commit -m "feat(llm): streaming for OpenAI platform + compatible adapters"
```

---

## Task 6: Anthropic adapter `stream()`

**Files:**
- Modify: `server/app/services/llm/adapters/anthropic_apikey.py`
- Test: `server/tests/test_llm_streaming.py`

- [ ] **Step 1: Write the failing test (fake SDK event stream)**

Append to `server/tests/test_llm_streaming.py`:

```python
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


@pytest.mark.asyncio
async def test_anthropic_adapter_stream_text(monkeypatch):
    import json as _json

    from app.models.llm_connector import LlmConnector
    from app.services.llm.adapters import anthropic_apikey

    class _FakeMessages:
        def stream(self, **kwargs):
            return _FakeAnthropicStream(_anthropic_text_events())

    class _FakeClient:
        def __init__(self, *a, **k):
            self.messages = _FakeMessages()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(anthropic_apikey, "AsyncAnthropic", _FakeClient)

    connector = LlmConnector(
        user_id=1,
        connector_type="anthropic_apikey",
        display_name="claude",
        status="active",
        credentials=_json.dumps({"api_key": "sk-ant-test"}),
        model_hint="claude-x",
    )
    adapter = anthropic_apikey.AnthropicApiKeyAdapter(connector)
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    chunks = [c async for c in adapter.stream(req)]
    assert "".join(c.text_delta for c in chunks) == "Hello"
    assert chunks[-1].done is True
    assert chunks[-1].stop_reason == "end_turn"
    assert chunks[-1].usage.completion == 5


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


@pytest.mark.asyncio
async def test_anthropic_adapter_stream_tool_use(monkeypatch):
    import json as _json

    from app.models.llm_connector import LlmConnector
    from app.services.llm.adapters import anthropic_apikey

    class _FakeMessages:
        def stream(self, **kwargs):
            return _FakeAnthropicStream(_anthropic_tool_events())

    class _FakeClient:
        def __init__(self, *a, **k):
            self.messages = _FakeMessages()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(anthropic_apikey, "AsyncAnthropic", _FakeClient)

    connector = LlmConnector(
        user_id=1,
        connector_type="anthropic_apikey",
        display_name="claude",
        status="active",
        credentials=_json.dumps({"api_key": "sk-ant-test"}),
        model_hint="claude-x",
    )
    adapter = anthropic_apikey.AnthropicApiKeyAdapter(connector)
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    chunks = [c async for c in adapter.stream(req)]

    # Reassemble tool-call fragments by index.
    frags = [d for c in chunks for d in c.tool_call_deltas]
    assert frags[0].id == "toolu_1" and frags[0].name == "search"
    joined = "".join(d.input_json_fragment for d in frags)
    assert _json.loads(joined) == {"q": "house"}
    assert chunks[-1].done is True
    assert chunks[-1].stop_reason == "tool_use"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py -k anthropic_adapter_stream -q`
Expected: FAIL — `StreamingUnsupported`

- [ ] **Step 3: Implement `stream()` in `anthropic_apikey.py`**

Add to imports (merge with existing):

```python
from collections.abc import AsyncIterator

from app.services.llm.base import (
    ChatRequest,
    ChatResponse,
    ChatResponseChunk,
    LlmAdapter,
    Message,
    TokenUsage,
    ToolCallDelta,
)
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
```

Add a module-level finish-reason map near `DEFAULT_MODEL`:

```python
_STREAM_FINISH_REASON = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
}
```

Add the method (after `health_check`):

```python
    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatResponseChunk]:
        model = request.model or self.connector.model_hint or DEFAULT_MODEL
        max_tokens = request.max_tokens or DEFAULT_MAX_TOKENS
        timeout = min(
            max(request.timeout_seconds or DEFAULT_TIMEOUT_SECONDS, 1.0),
            MAX_TIMEOUT_SECONDS,
        )

        anthropic_messages = to_anthropic_messages(request.messages)
        tools, choice = to_anthropic_tools(request.tools, request.force_tool)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }
        if request.system:
            kwargs["system"] = request.system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if tools:
            kwargs["tools"] = tools
        if choice is not None:
            kwargs["tool_choice"] = choice

        # Per-content-block index → tool id/name (sent once at block start).
        block_index_to_tool: dict[int, str] = {}
        stop_reason: str | None = None
        output_tokens: int | None = None

        try:
            async with self._client(timeout=timeout) as client:
                async with client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        etype = getattr(event, "type", None)
                        if etype == "content_block_start":
                            block = getattr(event, "content_block", None)
                            if getattr(block, "type", None) == "tool_use":
                                idx = int(getattr(event, "index", 0))
                                tool_id = getattr(block, "id", None)
                                name = getattr(block, "name", None)
                                block_index_to_tool[idx] = name or ""
                                yield ChatResponseChunk(
                                    tool_call_deltas=[
                                        ToolCallDelta(index=idx, id=tool_id, name=name)
                                    ]
                                )
                        elif etype == "content_block_delta":
                            delta = getattr(event, "delta", None)
                            dtype = getattr(delta, "type", None)
                            if dtype == "text_delta":
                                yield ChatResponseChunk(
                                    text_delta=getattr(delta, "text", "") or ""
                                )
                            elif dtype == "input_json_delta":
                                idx = int(getattr(event, "index", 0))
                                yield ChatResponseChunk(
                                    tool_call_deltas=[
                                        ToolCallDelta(
                                            index=idx,
                                            input_json_fragment=getattr(
                                                delta, "partial_json", ""
                                            )
                                            or "",
                                        )
                                    ]
                                )
                        elif etype == "message_delta":
                            delta = getattr(event, "delta", None)
                            sr = getattr(delta, "stop_reason", None)
                            if sr is not None:
                                stop_reason = sr
                            usage = getattr(event, "usage", None)
                            if usage is not None:
                                ot = getattr(usage, "output_tokens", None)
                                if ot is not None:
                                    output_tokens = int(ot)
        except APITimeoutError as exc:
            raise ProviderUnavailable("Upstream timeout") from exc
        except APIConnectionError as exc:
            raise ProviderUnavailable("Upstream network error") from exc
        except APIStatusError as exc:
            self._raise_for_status(exc)
        except APIError as exc:
            raise ProviderUnavailable(
                f"Anthropic API error: {type(exc).__name__}"
            ) from exc

        canonical_stop = _STREAM_FINISH_REASON.get(stop_reason or "", "end_turn")
        if block_index_to_tool and canonical_stop != "tool_use":
            canonical_stop = "tool_use"
        final_usage = (
            TokenUsage(prompt=0, completion=output_tokens)
            if output_tokens is not None
            else None
        )
        yield ChatResponseChunk(
            stop_reason=canonical_stop,
            usage=final_usage,
            done=True,
        )
```

Note: Anthropic streams `output_tokens` in `message_delta` but `input_tokens` only in `message_start.usage`. For the counts-only call log this completion count is sufficient; prompt is recorded as 0 when unavailable. (Documented as a design decision.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && .venv/bin/pytest tests/test_llm_streaming.py -k anthropic_adapter_stream -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/adapters/anthropic_apikey.py server/tests/test_llm_streaming.py
git commit -m "feat(llm): Anthropic provider-native streaming (text + tool_use deltas)"
```

---

## Task 7: `Gateway.stream` + `_attempt_stream` with counts-only logging

**Files:**
- Modify: `server/app/services/llm/gateway.py`
- Test: `server/tests/test_llm_gateway_stream.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_llm_gateway_stream.py
"""Tests for Gateway.stream — resolution mirrors dispatch, counts-only logging."""

from __future__ import annotations

import json

import pytest

from app.models.llm_connector import LlmCallLog, LlmConnector
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.base import ChatRequest, ChatResponseChunk, Message, TokenUsage
from app.services.llm.exceptions import NoLlmConfigured, ProviderUnavailable
from app.services.llm.gateway import Gateway


@pytest.fixture
def dj_user(db) -> User:
    user = User(
        username="streamdj",
        password_hash=get_password_hash("password123"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_connector(db, user, **kw) -> LlmConnector:
    row = LlmConnector(
        user_id=user.id,
        connector_type=kw.get("connector_type", "openai_apikey"),
        display_name=kw.get("display_name", "Test"),
        status=kw.get("status", "active"),
        credentials=json.dumps({"api_key": "sk-fake"}),
        model_hint="gpt-5-mini",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _fake_stream(chunks):
    async def _gen(self, request):
        for c in chunks:
            yield c

    return _gen


@pytest.mark.asyncio
async def test_stream_no_actor_no_default_raises(db):
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(NoLlmConfigured):
        async for _ in Gateway.stream(db, None, req, purpose="test"):
            pass


@pytest.mark.asyncio
async def test_stream_dispatches_and_logs_counts_only(db, dj_user, monkeypatch):
    connector = _make_connector(db, dj_user)
    chunks = [
        ChatResponseChunk(text_delta="Hel"),
        ChatResponseChunk(text_delta="lo"),
        ChatResponseChunk(
            stop_reason="end_turn",
            usage=TokenUsage(prompt=4, completion=2),
            done=True,
        ),
    ]
    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _fake_stream(chunks))

    req = ChatRequest(messages=[Message(role="user", content="hi")])
    out = [c async for c in Gateway.stream(db, dj_user, req, purpose="recommendation")]
    assert "".join(c.text_delta for c in out) == "Hello"

    log = db.query(LlmCallLog).filter(LlmCallLog.connector_id == connector.id).one()
    assert log.status == "ok"
    assert log.purpose == "recommendation"
    assert log.tokens_in == 4
    assert log.tokens_out == 2
    db.refresh(connector)
    assert connector.last_used_at is not None


@pytest.mark.asyncio
async def test_stream_error_logs_provider_unavailable(db, dj_user, monkeypatch):
    connector = _make_connector(db, dj_user)

    async def _boom(self, request):
        raise ProviderUnavailable("down")
        yield  # pragma: no cover

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _boom)

    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(ProviderUnavailable):
        async for _ in Gateway.stream(db, dj_user, req, purpose="test"):
            pass

    log = db.query(LlmCallLog).filter(LlmCallLog.connector_id == connector.id).one()
    assert log.status == "provider_unavailable"


@pytest.mark.asyncio
async def test_stream_consumer_cancel_logs_and_propagates(db, dj_user, monkeypatch):
    """Consumer stops early (client disconnect) → GeneratorExit, log written once."""
    connector = _make_connector(db, dj_user)

    async def _infinite(self, request):
        i = 0
        while True:
            yield ChatResponseChunk(text_delta=str(i))
            i += 1

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _infinite)

    req = ChatRequest(messages=[Message(role="user", content="hi")])
    agen = Gateway.stream(db, dj_user, req, purpose="test")
    first = await agen.__anext__()
    assert first.text_delta == "0"
    await agen.aclose()  # simulate client disconnect

    log = db.query(LlmCallLog).filter(LlmCallLog.connector_id == connector.id).one()
    assert log.status in ("ok", "cancelled")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_gateway_stream.py -q`
Expected: FAIL — `Gateway.stream` not defined

- [ ] **Step 3: Implement `Gateway.stream` + `_attempt_stream`**

Add imports at the top of `server/app/services/llm/gateway.py` (merge):

```python
from collections.abc import AsyncIterator

from app.services.llm.base import ChatRequest, ChatResponse, ChatResponseChunk
```

Add a `stream` staticmethod inside `class Gateway` (after `dispatch`):

```python
    @staticmethod
    async def stream(
        db: Session,
        actor: User | None,
        request: ChatRequest,
        *,
        purpose: str,
    ) -> AsyncIterator[ChatResponseChunk]:
        """Stream a chat response, mirroring ``dispatch`` resolution + logging.

        Resolution is identical to ``dispatch`` (per-DJ default → MRU → org
        default). Logging differs only in timing: a single counts-only
        ``llm_call_log`` row is written when the stream finishes (success),
        errors, or is cancelled by the consumer (client disconnect → the async
        generator is closed and ``GeneratorExit`` fires the ``finally``).

        Auto-fallback (``fallback_policy``) is intentionally NOT applied to
        streaming: chunks have already been delivered to the consumer by the
        time a mid-stream error surfaces, so transparently restarting on another
        connector would corrupt the output. Streaming always fails fast.
        """
        primary = _resolve_connector(db, actor)
        actor_id = actor.id if actor else _system_actor_id(db, primary)
        async for chunk in _attempt_stream(
            db, primary, request, purpose=purpose, actor_id=actor_id
        ):
            yield chunk
```

Add the module-level `_attempt_stream` async generator (after `_attempt`):

```python
async def _attempt_stream(
    db: Session,
    connector: LlmConnector,
    request: ChatRequest,
    *,
    purpose: str,
    actor_id: int,
) -> AsyncIterator[ChatResponseChunk]:
    """Run a single adapter stream, logging exactly one outcome row.

    The call log is written in a ``finally`` so it fires on success, on a typed
    error, AND on consumer cancellation (``GeneratorExit`` raised into the
    generator when the SSE client disconnects). The status reflects which path
    fired; counts come only from a terminal chunk's ``usage`` (never content).
    """
    adapter_cls = get_adapter_class(connector.connector_type)
    adapter = adapter_cls(connector)

    started = monotonic()
    status = "ok"
    error_code: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    auth_failed = False

    try:
        async for chunk in adapter.stream(request):
            if chunk.usage is not None:
                tokens_in = chunk.usage.prompt
                tokens_out = chunk.usage.completion
            yield chunk
    except GeneratorExit:
        # Consumer disconnected — record as cancelled and re-raise so the
        # adapter's own finally/cleanup closes the upstream connection.
        status = "cancelled"
        error_code = "client_disconnect"
        raise
    except AuthInvalid:
        status = "auth_invalid"
        error_code = "401"
        auth_failed = True
        raise
    except RateLimited as exc:
        status = "rate_limited"
        error_code = str(exc.retry_after_seconds or "")
        raise
    except QuotaExceeded:
        status = "quota_exceeded"
        error_code = "402"
        raise
    except ProviderUnavailable as exc:
        status = "provider_unavailable"
        error_code = type(exc).__name__
        raise
    except ToolTranslationError:
        status = "tool_translation_error"
        error_code = "translation"
        raise
    except LlmError:
        status = "error"
        error_code = "llm_error"
        raise
    finally:
        latency_ms = int((monotonic() - started) * 1000)
        if status == "ok":
            connector.last_used_at = utcnow()
            connector.last_error = None
        if auth_failed:
            connector.status = STATUS_AUTH_INVALID
            connector.last_error = "auth_invalid"
        log_call(
            db,
            connector_id=connector.id,
            purpose=purpose,
            status=status,
            latency_ms=latency_ms,
            tokens_in=tokens_in if status == "ok" else None,
            tokens_out=tokens_out if status == "ok" else None,
            error_code=error_code,
        )
        if auth_failed:
            audit_event(
                db,
                actor_user_id=actor_id,
                target_connector_id=connector.id,
                event_type=AUDIT_AUTH_INVALID_OBSERVED,
            )
        db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && .venv/bin/pytest tests/test_llm_gateway_stream.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add server/app/services/llm/gateway.py server/tests/test_llm_gateway_stream.py
git commit -m "feat(llm): Gateway.stream with counts-only logging + cancellation"
```

---

## Task 8: SSE backend endpoint `POST /api/llm/connectors/{id}/stream-test`

**Files:**
- Modify: `server/app/api/llm.py`
- Test: `server/tests/test_llm_stream_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_llm_stream_endpoint.py
"""SSE stream-test endpoint: auth, content-type, body shape, ownership."""

from __future__ import annotations

import json

import pytest

from app.models.llm_connector import LlmConnector
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.base import ChatResponseChunk, TokenUsage


def _make_connector(db, user) -> LlmConnector:
    row = LlmConnector(
        user_id=user.id,
        connector_type="openai_apikey",
        display_name="Test",
        status="active",
        credentials=json.dumps({"api_key": "sk-fake"}),
        model_hint="gpt-5-mini",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_stream_test_requires_auth(client, db, test_user):
    connector = _make_connector(db, test_user)
    resp = client.post(f"/api/llm/connectors/{connector.id}/stream-test")
    assert resp.status_code == 401


def test_stream_test_404_for_unowned(client, db, test_user, auth_headers):
    # Connector owned by a different user.
    from app.models.user import User
    from app.services.auth import get_password_hash

    other = User(username="other", password_hash=get_password_hash("x123456789"), role="dj")
    db.add(other)
    db.commit()
    db.refresh(other)
    connector = _make_connector(db, other)
    resp = client.post(
        f"/api/llm/connectors/{connector.id}/stream-test", headers=auth_headers
    )
    assert resp.status_code == 404


def test_stream_test_streams_chunks(client, db, test_user, auth_headers, monkeypatch):
    connector = _make_connector(db, test_user)

    async def _fake_stream(self, request):
        yield ChatResponseChunk(text_delta="Hi")
        yield ChatResponseChunk(text_delta=" there")
        yield ChatResponseChunk(
            stop_reason="end_turn", usage=TokenUsage(prompt=2, completion=2), done=True
        )

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _fake_stream)

    resp = client.post(
        f"/api/llm/connectors/{connector.id}/stream-test", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    # Each SSE event line starts with "data:". Reconstruct the JSON payloads.
    payloads = [
        json.loads(line[len("data:") :].strip())
        for line in body.splitlines()
        if line.startswith("data:")
    ]
    text = "".join(p.get("text_delta", "") for p in payloads)
    assert "Hi there" in text
    assert any(p.get("done") for p in payloads)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && .venv/bin/pytest tests/test_llm_stream_endpoint.py -q`
Expected: FAIL — 404/405 (endpoint missing)

- [ ] **Step 3: Implement the SSE endpoint in `llm.py`**

Add imports (merge with existing):

```python
import json as _json

from sse_starlette.sse import EventSourceResponse

from app.models.user import User
from app.services.llm.base import ChatRequest, Message
from app.services.llm.exceptions import LlmError, NoLlmConfigured
from app.services.llm.gateway import Gateway
```

Add the endpoint (place after `test_connector`):

```python
# A short, fixed prompt for the streaming health probe. Streams a single
# sentence so the DJ sees tokens arrive in real time, exercising the full
# resolve → adapter.stream → SSE path end-to-end.
_STREAM_TEST_PROMPT = "Reply with one short friendly sentence confirming you are online."


@router.post("/connectors/{connector_id}/stream-test")
@limiter.limit("10/minute")
async def stream_test_connector(
    request: FastAPIRequest,
    connector_id: int,
    user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """Stream a short sentence through the connector as ``text/event-stream``.

    Validates ownership up front (404 for connectors the DJ doesn't own — never
    leaks existence). Each SSE ``data:`` frame is a JSON ``ChatResponseChunk``.
    On a typed gateway error, a terminal ``event: error`` frame is emitted with a
    sanitised code (never the upstream payload), then the stream ends. Client
    disconnect cancels the upstream provider request (the gateway generator's
    ``finally`` writes the counts-only call log + closes the adapter).
    """
    row = _get_owned_connector_or_404(db, connector_id, user.id)

    chat_request = ChatRequest(
        messages=[Message(role="user", content=_STREAM_TEST_PROMPT)],
        max_tokens=64,
        temperature=0.0,
        model=row.model_hint or None,
    )

    async def _publisher():
        try:
            async for chunk in Gateway.stream(
                db, user, chat_request, purpose="stream_test"
            ):
                yield {"data": _json.dumps(chunk.model_dump())}
        except NoLlmConfigured:
            yield {"event": "error", "data": _json.dumps({"code": "no_connector"})}
        except LlmError as exc:
            # Map to a sanitised, stable code — never echo the provider message.
            code = type(exc).__name__
            logger.info("stream-test failed for connector %s: %s", connector_id, code)
            yield {"event": "error", "data": _json.dumps({"code": code})}

    return EventSourceResponse(
        _publisher(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && .venv/bin/pytest tests/test_llm_stream_endpoint.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add server/app/api/llm.py server/tests/test_llm_stream_endpoint.py
git commit -m "feat(api): authenticated SSE stream-test endpoint for connectors"
```

---

## Task 9: Backend CI green (ruff / format / bandit / full pytest)

**Files:** none new — fix-ups only.

- [ ] **Step 1: Auto-format + lint-fix**

Run: `cd server && .venv/bin/ruff format . && .venv/bin/ruff check --fix .`

- [ ] **Step 2: Lint check**

Run: `cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: no errors. If `_normalise_finish_reason` import triggers a private-import lint (PLC2701), keep the `# noqa` already added in Task 3, or inline a local copy of the 4-line mapping function into `streaming.py` to avoid importing a private name.

- [ ] **Step 3: Bandit**

Run: `cd server && .venv/bin/bandit -r app -c pyproject.toml -q`
Expected: no new findings (the `# nosec B106` on the Authorization header is preserved).

- [ ] **Step 4: Full backend test suite + coverage gate**

Run: `cd server && .venv/bin/pytest --tb=short -q`
Expected: PASS, coverage ≥ gate. If new streaming files drag coverage, the dedicated stream tests above should cover them; add targeted tests for any uncovered branch the report flags.

- [ ] **Step 5: Commit any fix-ups**

```bash
git add -A
git commit -m "chore(llm): backend lint/format/coverage fix-ups for streaming"
```

---

## Task 10: Frontend SSE consumer `streamConnectorTest`

**Files:**
- Modify: `dashboard/lib/api.ts`
- Test: `dashboard/lib/__tests__/api.test.ts` (append)

- [ ] **Step 1: Write the failing test**

Append to `dashboard/lib/__tests__/api.test.ts` (match the file's existing import + setup style):

```typescript
describe('streamConnectorTest', () => {
  it('parses SSE data frames and invokes onChunk per frame', async () => {
    const sse =
      'data: {"text_delta":"Hi","done":false}\n\n' +
      'data: {"text_delta":" there","done":false}\n\n' +
      'data: {"text_delta":"","stop_reason":"end_turn","done":true}\n\n';
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(sse));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    apiClient.setToken('jwt-token');
    const chunks: Array<{ text_delta?: string; done?: boolean }> = [];
    await apiClient.streamConnectorTest(7, (c) => chunks.push(c));

    expect(chunks.map((c) => c.text_delta).join('')).toBe('Hi there');
    expect(chunks.at(-1)?.done).toBe(true);
    // Auth header present.
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get('Authorization')).toBe('Bearer jwt-token');
    vi.unstubAllGlobals();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dashboard && npm test -- --run lib/__tests__/api.test.ts`
Expected: FAIL — `apiClient.streamConnectorTest is not a function`

- [ ] **Step 3: Add the type + method to `api.ts`**

Add near the other LLM types (search for `LlmConnectorTestResult`):

```typescript
export interface LlmStreamChunk {
  text_delta?: string;
  tool_call_deltas?: Array<{
    index: number;
    id?: string | null;
    name?: string | null;
    input_json_fragment?: string;
  }>;
  stop_reason?: 'end_turn' | 'tool_use' | 'max_tokens' | 'error' | null;
  usage?: { prompt: number; completion: number } | null;
  done?: boolean;
}
```

Add the method to the `ApiClient` class (near `testLlmConnector`):

```typescript
  /**
   * Stream a short health-check sentence through a connector via SSE.
   *
   * Uses fetch + ReadableStream rather than EventSource because EventSource
   * cannot send the Authorization header this authenticated endpoint requires.
   * Pass an AbortSignal to cancel — aborting closes the connection, which the
   * backend treats as a client disconnect and cancels the upstream provider
   * request. ``onChunk`` is invoked for every parsed SSE data frame.
   */
  async streamConnectorTest(
    id: number,
    onChunk: (chunk: LlmStreamChunk) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const headers = new Headers({ Accept: 'text/event-stream' });
    if (this.token) headers.set('Authorization', `Bearer ${this.token}`);

    const response = await fetch(
      `${getApiUrl()}/api/llm/connectors/${id}/stream-test`,
      { method: 'POST', headers, signal },
    );
    if (!response.ok || !response.body) {
      if (response.status === 401 && this.onUnauthorized) this.onUnauthorized();
      throw new ApiError('Stream test failed', response.status);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are separated by a blank line.
        let sep: number;
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          for (const line of frame.split('\n')) {
            if (!line.startsWith('data:')) continue;
            const data = line.slice('data:'.length).trim();
            if (!data || data === '[DONE]') continue;
            try {
              onChunk(JSON.parse(data) as LlmStreamChunk);
            } catch {
              // Ignore unparseable keepalive frames.
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dashboard && npm test -- --run lib/__tests__/api.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/api.ts dashboard/lib/__tests__/api.test.ts
git commit -m "feat(ai-ui): SSE stream consumer for connector stream-test"
```

---

## Task 11: Minimal UI consumer wiring (admin/ai stream test) + scope note

**Files:**
- Modify: `dashboard/app/admin/ai/page.tsx`

**Decision:** The recommendation flow is a backend background pipeline that returns a final JSON payload to the UI (not a live token feed), so retrofitting it to SSE would be a large, risky change outside this issue's intent. Per the issue's "use reasonable judgment on scope and document it", the frontend consumer is the reusable `apiClient.streamConnectorTest` plumbing (Task 10) plus a minimal live "Stream test" affordance on the existing AI settings surface. The recommendation UI migration to SSE is explicitly deferred (future set-builder UI, §11.6) and noted in the PR body.

- [ ] **Step 1: Read the admin/ai page to find the connector row / actions area**

Run: `cd dashboard && grep -n "testLlmConnector\|Test\|connector" app/admin/ai/page.tsx | head -30`

- [ ] **Step 2: Add a "Stream test" button that appends streamed text into local state**

Add (adapt names to the file's existing component structure — this is the behavior to wire, not a verbatim drop-in):

```tsx
// Local state near the component's other useState hooks:
const [streamText, setStreamText] = useState<string>('');
const [streaming, setStreaming] = useState<number | null>(null);

async function handleStreamTest(connectorId: number) {
  setStreamText('');
  setStreaming(connectorId);
  try {
    await apiClient.streamConnectorTest(connectorId, (chunk) => {
      if (chunk.text_delta) setStreamText((prev) => prev + chunk.text_delta);
    });
  } catch {
    setStreamText('(stream test failed)');
  } finally {
    setStreaming(null);
  }
}
```

And in the per-connector action area, next to the existing test button:

```tsx
<button
  type="button"
  onClick={() => handleStreamTest(connector.id)}
  disabled={streaming !== null}
>
  {streaming === connector.id ? 'Streaming…' : 'Stream test'}
</button>
{streaming === connector.id && streamText && (
  <p style={{ marginTop: 8, opacity: 0.8 }}>{streamText}</p>
)}
```

- [ ] **Step 3: Type-check + existing page tests**

Run: `cd dashboard && npx tsc --noEmit`
Run: `cd dashboard && npm test -- --run app/admin/ai`
Expected: PASS. If the admin/ai page has snapshot/DOM tests that assert exact button sets, update those fixtures to include the new button.

- [ ] **Step 4: Commit**

```bash
git checkout dashboard/next-env.d.ts 2>/dev/null || true
git add dashboard/app/admin/ai/page.tsx
git commit -m "feat(ai-ui): minimal live stream-test affordance on AI settings"
```

---

## Task 12: Full local CI sweep + finishing the branch

**Files:** none new.

- [ ] **Step 1: Backend CI**

Run from `server/`:
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/pytest --tb=short -q
```
Expected: all green, coverage gate satisfied.

- [ ] **Step 2: Frontend CI**

Run from `dashboard/`:
```bash
npm run lint
npx tsc --noEmit
npm test -- --run
```
Expected: all green. Then `git checkout dashboard/next-env.d.ts` if auto-modified.

- [ ] **Step 3: Confirm no Alembic migration was introduced**

Run: `cd server && git diff --name-only origin/epic/ai-engine...HEAD | grep alembic || echo "no migrations — correct"`
Expected: `no migrations — correct` (streaming requires no schema change).

- [ ] **Step 4: Use superpowers:finishing-a-development-branch (option 2: Push + PR)**

Create the PR with `gh pr create --base epic/ai-engine`. PR body must include `Closes #335`, a `## Design decisions` section, and a note that the PR targets `epic/ai-engine`.

---

## Self-Review

**Spec coverage (issue #335 acceptance criteria):**
- `Gateway.stream(...) -> AsyncIterator[ChatResponseChunk]` → Task 7. ✅
- `ChatResponseChunk` carries incremental text + partial tool_calls + final stop_reason + usage → Task 1 (model), Tasks 3/4/6 (population). ✅
- Each adapter implements provider-native streaming (OpenAI, Anthropic, OpenAI-compatible) → Tasks 5, 6. ✅
- Non-streaming adapters degrade gracefully (`StreamingUnsupported`) → Tasks 1, 2. ✅
- SSE backend endpoint (text/event-stream) → Task 8. ✅
- Tool-use mid-stream parses across providers (OpenAI partial JSON, Anthropic delta blocks) → Task 3 (OpenAI tool frags), Task 6 (`input_json_delta`). ✅
- Cancellation propagates upstream (frontend disconnect → adapter cancels upstream) → Task 7 (`GeneratorExit` → adapter `async with` cleanup closes httpx/SDK stream), Task 10 (`AbortSignal`). ✅
- Counts-only call log + audit consistency with non-stream path → Task 7 `_attempt_stream`. ✅
- Frontend consumer → Tasks 10 (plumbing) + 11 (minimal UI, recommendation-migration deferral documented). ✅

**Placeholder scan:** No TBD/TODO. Frontend Task 11 step 2 is explicitly behavior-to-wire (adapt to existing component) because the exact JSX scaffold depends on the live file — the implementer reads it in step 1.

**Type consistency:** `ChatResponseChunk` fields (`text_delta`, `tool_call_deltas`, `stop_reason`, `usage`, `done`) and `ToolCallDelta` fields (`index`, `id`, `name`, `input_json_fragment`) are used identically in base.py, streaming.py, adapters, gateway, endpoint, and frontend type. `stream_openai_chat` signature matches its callers in both OpenAI adapters. `Gateway.stream` / `_attempt_stream` signatures match `dispatch` / `_attempt`.
