"""Tests for per-DJ monthly token caps (issue #339)."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.time import utcnow
from app.models.llm_connector import LlmCallLog, LlmConnector
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.base import ChatRequest, ChatResponse, Message, TokenUsage
from app.services.llm.connector_storage import (
    current_month_token_usage,
    set_monthly_cap,
)
from app.services.llm.exceptions import LlmError, QuotaCapReached
from app.services.llm.gateway import Gateway


def _make_dj(db, username="capdj"):
    user = User(username=username, password_hash=get_password_hash("password123"), role="dj")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_connector(db, user, *, monthly_token_cap=None):
    row = LlmConnector(
        user_id=user.id,
        connector_type="openai_apikey",
        display_name="Cap connector",
        status="active",
        credentials=json.dumps({"api_key": "sk-fake-key"}),
        model_hint="gpt-5-mini",
        monthly_token_cap=monthly_token_cap,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _log(db, connector_id, *, tokens_in, tokens_out, when=None):
    row = LlmCallLog(
        connector_id=connector_id,
        purpose="test",
        status="ok",
        latency_ms=10,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    db.add(row)
    db.flush()
    if when is not None:
        row.created_at = when
    db.commit()
    return row


def _req() -> ChatRequest:
    return ChatRequest(messages=[Message(role="user", content="hi")])


# --- Exception ---------------------------------------------------------------


def test_quota_cap_reached_is_llm_error():
    exc = QuotaCapReached("cap reached")
    assert isinstance(exc, LlmError)
    assert str(exc) == "cap reached"


# --- Model column ------------------------------------------------------------


def test_connector_defaults_to_no_cap(db):
    user = _make_dj(db)
    connector = _make_connector(db, user)
    assert connector.monthly_token_cap is None


def test_connector_stores_cap(db):
    user = _make_dj(db, username="capdj2")
    connector = _make_connector(db, user, monthly_token_cap=100_000)
    db.refresh(connector)
    assert connector.monthly_token_cap == 100_000


# --- Aggregation + setter helpers --------------------------------------------


def test_current_month_usage_sums_in_and_out(db):
    user = _make_dj(db, username="usagedj")
    connector = _make_connector(db, user)
    _log(db, connector.id, tokens_in=100, tokens_out=50)
    _log(db, connector.id, tokens_in=10, tokens_out=5)
    assert current_month_token_usage(db, connector.id) == 165


def test_current_month_usage_excludes_prior_months(db):
    user = _make_dj(db, username="usagedj2")
    connector = _make_connector(db, user)
    # 40 days ago — previous month, must be excluded.
    _log(db, connector.id, tokens_in=1000, tokens_out=1000, when=utcnow() - timedelta(days=40))
    _log(db, connector.id, tokens_in=7, tokens_out=3)
    assert current_month_token_usage(db, connector.id) == 10


def test_current_month_usage_treats_null_tokens_as_zero(db):
    user = _make_dj(db, username="usagedj3")
    connector = _make_connector(db, user)
    _log(db, connector.id, tokens_in=None, tokens_out=None)
    _log(db, connector.id, tokens_in=5, tokens_out=None)
    assert current_month_token_usage(db, connector.id) == 5


def test_current_month_usage_zero_when_no_rows(db):
    user = _make_dj(db, username="usagedj4")
    connector = _make_connector(db, user)
    assert current_month_token_usage(db, connector.id) == 0


def test_set_monthly_cap_accepts_positive_int(db):
    user = _make_dj(db, username="capset")
    connector = _make_connector(db, user)
    set_monthly_cap(connector, 50_000)
    assert connector.monthly_token_cap == 50_000


def test_set_monthly_cap_accepts_none_to_clear(db):
    user = _make_dj(db, username="capclear")
    connector = _make_connector(db, user, monthly_token_cap=10)
    set_monthly_cap(connector, None)
    assert connector.monthly_token_cap is None


def test_set_monthly_cap_rejects_negative(db):
    user = _make_dj(db, username="capneg")
    connector = _make_connector(db, user)
    with pytest.raises(ValueError):
        set_monthly_cap(connector, -1)


# --- Gateway pre-flight enforcement ------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_allows_when_under_cap(db):
    user = _make_dj(db, username="undercap")
    connector = _make_connector(db, user, monthly_token_cap=1_000)
    _log(db, connector.id, tokens_in=100, tokens_out=100)  # 200 used, under 1000

    fake = ChatResponse(
        text="ok",
        tool_calls=[],
        stop_reason="end_turn",
        usage=TokenUsage(prompt=5, completion=2),
    )
    with patch.object(OpenAIApiKeyAdapter, "chat", new=AsyncMock(return_value=fake)):
        resp = await Gateway.dispatch(db, user, _req(), purpose="test")
    assert resp.text == "ok"


@pytest.mark.asyncio
async def test_dispatch_refuses_when_cap_reached(db):
    user = _make_dj(db, username="atcap")
    connector = _make_connector(db, user, monthly_token_cap=200)
    _log(db, connector.id, tokens_in=150, tokens_out=50)  # 200 used, == cap

    # The adapter must NOT be called — refusal is pre-flight.
    chat_mock = AsyncMock()
    with patch.object(OpenAIApiKeyAdapter, "chat", new=chat_mock):
        with pytest.raises(QuotaCapReached):
            await Gateway.dispatch(db, user, _req(), purpose="test")
    chat_mock.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_unlimited_when_cap_none(db):
    user = _make_dj(db, username="nolimit")
    connector = _make_connector(db, user, monthly_token_cap=None)
    _log(db, connector.id, tokens_in=10_000, tokens_out=10_000)

    fake = ChatResponse(
        text="ok",
        tool_calls=[],
        stop_reason="end_turn",
        usage=TokenUsage(prompt=1, completion=1),
    )
    with patch.object(OpenAIApiKeyAdapter, "chat", new=AsyncMock(return_value=fake)):
        resp = await Gateway.dispatch(db, user, _req(), purpose="test")
    assert resp.text == "ok"
