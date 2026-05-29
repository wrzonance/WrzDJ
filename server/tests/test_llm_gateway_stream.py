"""Tests for Gateway.stream — resolution mirrors dispatch, counts-only logging."""

from __future__ import annotations

import json

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


async def test_stream_no_actor_no_default_raises(db):
    req = ChatRequest(messages=[Message(role="user", content="hi")])
    with pytest.raises(NoLlmConfigured):
        async for _ in Gateway.stream(db, None, req, purpose="test"):
            pass


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
