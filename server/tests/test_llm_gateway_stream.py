"""Tests for Gateway.stream — resolution mirrors dispatch, counts-only logging."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest

from app.models.llm_connector import LlmCallLog, LlmConnector
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.base import ChatRequest, ChatResponseChunk, Message, TokenUsage
from app.services.llm.exceptions import (
    AuthInvalid,
    NoLlmConfigured,
    ProviderUnavailable,
    QuotaCapReached,
    ToolTranslationError,
)
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


class _MalformedStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.status_code = 200

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


class _MalformedStreamClient:
    def __init__(self, response: _MalformedStreamResponse) -> None:
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        client = self

        class _Context:
            async def __aenter__(self):
                return client._response

            async def __aexit__(self, *exc):
                return False

        return _Context()


async def test_stream_no_actor_no_default_raises(db):
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(NoLlmConfigured):
        async for _ in Gateway.stream(db, None, req, purpose="test"):
            pass


async def test_stream_rejects_explicit_connector_owned_by_another_dj(db, dj_user):
    from app.services.llm.exceptions import NoLlmConfigured

    _make_connector(db, dj_user, display_name="DJ default")
    other_user = User(
        username="other-stream-dj",
        password_hash=get_password_hash("password123"),
        role="dj",
    )
    db.add(other_user)
    db.commit()
    foreign_connector = _make_connector(db, other_user, display_name="Foreign")

    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(NoLlmConfigured, match="selected connector is unavailable"):
        async for _ in Gateway.stream(
            db,
            dj_user,
            req,
            purpose="stream_test",
            connector_id=foreign_connector.id,
        ):
            pass


@pytest.mark.parametrize("explicit_connector", [True, False], ids=["explicit", "dj-default"])
async def test_stream_enforces_monthly_cap_before_provider_or_telemetry(
    db, dj_user, monkeypatch, explicit_connector
):
    # Regression for 57cfcdc6867f: stream must enforce the resolved connector's
    # cap before provider I/O, matching dispatch for explicit and default routes.
    connector = _make_connector(db, dj_user)
    connector.monthly_token_cap = 0
    if not explicit_connector:
        connector.is_default = True
    db.commit()
    provider_called = False

    async def _provider_stream(self, request):
        nonlocal provider_called
        provider_called = True
        yield ChatResponseChunk(text_delta="unexpected")

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _provider_stream)
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    connector_id = connector.id if explicit_connector else None

    with pytest.raises(QuotaCapReached):
        async for _ in Gateway.stream(
            db,
            dj_user,
            req,
            purpose="test",
            connector_id=connector_id,
        ):
            pass

    assert provider_called is False
    assert db.query(LlmCallLog).filter(LlmCallLog.connector_id == connector.id).count() == 0


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


async def test_stream_malformed_provider_choice_is_typed_and_does_not_mark_success(
    db, dj_user, monkeypatch
):
    connector = _make_connector(db, dj_user)
    previous_last_used = datetime(2020, 1, 1)
    connector.last_used_at = previous_last_used
    connector.last_error = "previous_error"
    db.commit()

    from app.services.llm.adapters import _httpx_openai

    response = _MalformedStreamResponse(
        [
            'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}',
            "",
            'data: {"choices":[null]}',
            "",
        ]
    )
    monkeypatch.setattr(
        _httpx_openai.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _MalformedStreamClient(response),
    )

    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(ToolTranslationError, match="Upstream returned malformed streaming data"):
        async for _ in Gateway.stream(db, dj_user, req, purpose="test"):
            pass

    log = db.query(LlmCallLog).filter(LlmCallLog.connector_id == connector.id).one()
    assert log.status == "tool_translation_error"
    assert log.error_code == "translation"
    db.refresh(connector)
    assert connector.last_used_at == previous_last_used
    assert connector.last_error == "previous_error"


async def test_unexpected_stream_error_after_usage_is_not_recorded_as_success(
    db, dj_user, monkeypatch
):
    connector = _make_connector(db, dj_user)
    previous_last_used = datetime(2020, 1, 1)
    connector.last_used_at = previous_last_used
    connector.last_error = "previous_error"
    db.commit()

    async def _unexpected_failure(self, request):
        yield ChatResponseChunk(usage=TokenUsage(prompt=4, completion=2))
        raise RuntimeError("provider payload contained a private value")

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _unexpected_failure)

    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(ProviderUnavailable, match="Upstream stream failed") as exc_info:
        async for _ in Gateway.stream(db, dj_user, req, purpose="test"):
            pass
    assert exc_info.value.__cause__ is None
    assert "private value" not in str(exc_info.value)

    log = db.query(LlmCallLog).filter(LlmCallLog.connector_id == connector.id).one()
    assert log.status == "error"
    assert log.error_code == "RuntimeError"
    assert log.tokens_in is None
    assert log.tokens_out is None
    db.refresh(connector)
    assert connector.last_used_at == previous_last_used
    assert connector.last_error == "previous_error"


async def test_stream_auth_error_marks_connector_and_audits(db, dj_user, monkeypatch):
    from app.models.llm_connector import (
        AUDIT_AUTH_INVALID_OBSERVED,
        STATUS_AUTH_INVALID,
        LlmAuditEvent,
    )

    connector = _make_connector(db, dj_user)

    async def _auth(self, request):
        raise AuthInvalid("nope")
        yield  # pragma: no cover

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _auth)

    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(AuthInvalid):
        async for _ in Gateway.stream(db, dj_user, req, purpose="test"):
            pass

    db.refresh(connector)
    assert connector.status == STATUS_AUTH_INVALID
    log = db.query(LlmCallLog).filter(LlmCallLog.connector_id == connector.id).one()
    assert log.status == "auth_invalid"
    audit = (
        db.query(LlmAuditEvent)
        .filter(
            LlmAuditEvent.target_connector_id == connector.id,
            LlmAuditEvent.event_type == AUDIT_AUTH_INVALID_OBSERVED,
        )
        .one()
    )
    assert audit is not None


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
    assert log.status == "cancelled"
    assert log.error_code == "client_disconnect"


async def test_stream_task_cancellation_records_partial_usage_without_marking_used(
    db, dj_user, monkeypatch
):
    # Regression for 57cfcdc6867f: task cancellation during an awaited provider
    # read must not record a successful call or advance connector last-used time.
    connector = _make_connector(db, dj_user)
    previous_last_used = datetime(2020, 1, 1)
    connector.last_used_at = previous_last_used
    db.commit()
    waiting_for_provider = asyncio.Event()

    async def _partial_then_wait(self, request):
        yield ChatResponseChunk(
            text_delta="partial",
            usage=TokenUsage(prompt=7, completion=3),
        )
        waiting_for_provider.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(OpenAIApiKeyAdapter, "stream", _partial_then_wait)

    req = ChatRequest(messages=[Message(role="user", content="hi")])

    async def _consume() -> None:
        async for _ in Gateway.stream(db, dj_user, req, purpose="test"):
            pass

    task = asyncio.create_task(_consume())
    await waiting_for_provider.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    log = db.query(LlmCallLog).filter(LlmCallLog.connector_id == connector.id).one()
    assert log.status == "cancelled"
    assert log.error_code == "task_cancelled"
    assert log.tokens_in == 7
    assert log.tokens_out == 3
    db.refresh(connector)
    assert connector.last_used_at == previous_last_used
