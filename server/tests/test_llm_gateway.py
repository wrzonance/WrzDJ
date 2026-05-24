"""Tests for the LLM gateway dispatch + connector resolution."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.models.llm_connector import LlmConnector
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.base import ChatRequest, ChatResponse, Message, TokenUsage
from app.services.llm.exceptions import (
    AuthInvalid,
    NoLlmConfigured,
    ProviderUnavailable,
    RateLimited,
)
from app.services.llm.gateway import Gateway


@pytest.fixture
def dj_user(db) -> User:
    user = User(
        username="djuser",
        password_hash=get_password_hash("password123"),
        role="dj",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user_actor(db) -> User:
    user = User(
        username="adminactor",
        password_hash=get_password_hash("password123"),
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_connector(
    db,
    user: User,
    *,
    connector_type: str = "openai_apikey",
    display_name: str = "Test connector",
    status: str = "active",
    model_hint: str = "gpt-5-mini",
) -> LlmConnector:
    row = LlmConnector(
        user_id=user.id,
        connector_type=connector_type,
        display_name=display_name,
        status=status,
        credentials=json.dumps({"api_key": "sk-fake-key"}),
        model_hint=model_hint,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def gateway_request() -> ChatRequest:
    return ChatRequest(messages=[Message(role="user", content="hi")])


@pytest.mark.asyncio
async def test_no_actor_no_default_raises(db, gateway_request):
    with pytest.raises(NoLlmConfigured):
        await Gateway.dispatch(db, None, gateway_request, purpose="test")


@pytest.mark.asyncio
async def test_actor_with_active_connector_dispatches(db, dj_user, gateway_request):
    connector = _make_connector(db, dj_user)

    fake_response = ChatResponse(
        text="ok",
        tool_calls=[],
        stop_reason="end_turn",
        usage=TokenUsage(prompt=5, completion=2),
    )

    with patch.object(
        __import__(
            "app.services.llm.adapters.openai_apikey",
            fromlist=["OpenAIApiKeyAdapter"],
        ).OpenAIApiKeyAdapter,
        "chat",
        new=AsyncMock(return_value=fake_response),
    ):
        resp = await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")

    assert resp.text == "ok"
    db.refresh(connector)
    assert connector.last_used_at is not None
    # call log row was inserted
    from app.models.llm_connector import LlmCallLog

    log = db.query(LlmCallLog).filter(LlmCallLog.connector_id == connector.id).one()
    assert log.status == "ok"
    assert log.tokens_in == 5
    assert log.tokens_out == 2


@pytest.mark.asyncio
async def test_auth_invalid_marks_connector(db, dj_user, gateway_request):
    connector = _make_connector(db, dj_user)
    with patch.object(
        __import__(
            "app.services.llm.adapters.openai_apikey",
            fromlist=["OpenAIApiKeyAdapter"],
        ).OpenAIApiKeyAdapter,
        "chat",
        new=AsyncMock(side_effect=AuthInvalid("nope")),
    ):
        with pytest.raises(AuthInvalid):
            await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")

    db.refresh(connector)
    assert connector.status == "auth_invalid"

    from app.models.llm_connector import LlmAuditEvent, LlmCallLog

    log = db.query(LlmCallLog).one()
    assert log.status == "auth_invalid"

    audit = db.query(LlmAuditEvent).one()
    assert audit.event_type == "auth_invalid_observed"
    assert audit.target_connector_id == connector.id


@pytest.mark.asyncio
async def test_rate_limited_logs_and_raises(db, dj_user, gateway_request):
    _make_connector(db, dj_user)
    with patch.object(
        __import__(
            "app.services.llm.adapters.openai_apikey",
            fromlist=["OpenAIApiKeyAdapter"],
        ).OpenAIApiKeyAdapter,
        "chat",
        new=AsyncMock(side_effect=RateLimited("slow", retry_after_seconds=12)),
    ):
        with pytest.raises(RateLimited) as exc_info:
            await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")
    assert exc_info.value.retry_after_seconds == 12

    from app.models.llm_connector import LlmCallLog

    log = db.query(LlmCallLog).one()
    assert log.status == "rate_limited"


@pytest.mark.asyncio
async def test_provider_unavailable_logs_and_raises(db, dj_user, gateway_request):
    _make_connector(db, dj_user)
    with patch.object(
        __import__(
            "app.services.llm.adapters.openai_apikey",
            fromlist=["OpenAIApiKeyAdapter"],
        ).OpenAIApiKeyAdapter,
        "chat",
        new=AsyncMock(side_effect=ProviderUnavailable("nope")),
    ):
        with pytest.raises(ProviderUnavailable):
            await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")

    from app.models.llm_connector import LlmCallLog

    log = db.query(LlmCallLog).one()
    assert log.status == "provider_unavailable"


@pytest.mark.asyncio
async def test_disabled_connector_skipped_in_resolution(db, dj_user, gateway_request):
    # Disabled connector should NOT be returned by the resolver — no default → raise.
    _make_connector(db, dj_user, status="disabled", display_name="Disabled")
    with pytest.raises(NoLlmConfigured):
        await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")


@pytest.mark.asyncio
async def test_falls_back_to_system_default(db, admin_user_actor, gateway_request):
    # admin has no connector of their own — falls back to system default.
    other_admin = User(
        username="otheradmin",
        password_hash=get_password_hash("password123"),
        role="admin",
    )
    db.add(other_admin)
    db.commit()
    db.refresh(other_admin)
    default_connector = _make_connector(db, other_admin, display_name="default-org-connector")

    # Wire the system default
    ss = db.query(SystemSettings).first()
    if ss is None:
        ss = SystemSettings(id=1, llm_default_connector_id=default_connector.id)
        db.add(ss)
    else:
        ss.llm_default_connector_id = default_connector.id
    db.commit()

    fake_response = ChatResponse(
        text="ok",
        tool_calls=[],
        stop_reason="end_turn",
        usage=TokenUsage(prompt=1, completion=1),
    )

    with patch.object(
        __import__(
            "app.services.llm.adapters.openai_apikey",
            fromlist=["OpenAIApiKeyAdapter"],
        ).OpenAIApiKeyAdapter,
        "chat",
        new=AsyncMock(return_value=fake_response),
    ):
        resp = await Gateway.dispatch(db, None, gateway_request, purpose="test")

    assert resp.text == "ok"


@pytest.mark.asyncio
async def test_mru_resolution_picks_recent(db, dj_user, gateway_request):
    """Resolver picks the connector with the most recent last_used_at."""
    from app.core.time import utcnow

    older = _make_connector(db, dj_user, display_name="older")
    newer = _make_connector(db, dj_user, display_name="newer")

    older.last_used_at = None
    from datetime import timedelta

    newer.last_used_at = utcnow() - timedelta(seconds=10)
    db.commit()

    fake_response = ChatResponse(
        text="ok",
        tool_calls=[],
        stop_reason="end_turn",
        usage=None,
    )

    with patch.object(
        __import__(
            "app.services.llm.adapters.openai_apikey",
            fromlist=["OpenAIApiKeyAdapter"],
        ).OpenAIApiKeyAdapter,
        "chat",
        new=AsyncMock(return_value=fake_response),
    ) as chat_mock:
        await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")

    chat_mock.assert_awaited_once()
    # Make sure the newer one was chosen
    db.refresh(newer)
    db.refresh(older)
    assert newer.last_used_at is not None
    # older.last_used_at was never set so should still be None
    assert older.last_used_at is None
