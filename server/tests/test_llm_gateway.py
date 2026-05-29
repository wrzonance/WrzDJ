"""Tests for the LLM gateway dispatch + connector resolution."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.models.llm_connector import LlmConnector
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.services.auth import get_password_hash
from app.services.llm.adapters.openai_apikey import OpenAIApiKeyAdapter
from app.services.llm.base import ChatRequest, ChatResponse, Message, TokenUsage
from app.services.llm.exceptions import (
    AuthInvalid,
    NoLlmConfigured,
    ProviderUnavailable,
    RateLimited,
)
from app.services.llm.gateway import Gateway


def _patch_chat(mock):
    """Patch the (only) adapter the gateway dispatches to in these tests."""
    return patch.object(OpenAIApiKeyAdapter, "chat", new=mock)


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

    with _patch_chat(AsyncMock(return_value=fake_response)):
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
    with _patch_chat(AsyncMock(side_effect=AuthInvalid("nope"))):
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
    with _patch_chat(AsyncMock(side_effect=RateLimited("slow", retry_after_seconds=12))):
        with pytest.raises(RateLimited) as exc_info:
            await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")
    assert exc_info.value.retry_after_seconds == 12

    from app.models.llm_connector import LlmCallLog

    log = db.query(LlmCallLog).one()
    assert log.status == "rate_limited"


@pytest.mark.asyncio
async def test_provider_unavailable_logs_and_raises(db, dj_user, gateway_request):
    _make_connector(db, dj_user)
    with _patch_chat(AsyncMock(side_effect=ProviderUnavailable("nope"))):
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

    with _patch_chat(AsyncMock(return_value=fake_response)):
        resp = await Gateway.dispatch(db, None, gateway_request, purpose="test")

    assert resp.text == "ok"


def _wire_system_default(db, connector: LlmConnector) -> None:
    ss = db.query(SystemSettings).first()
    if ss is None:
        ss = SystemSettings(id=1, llm_default_connector_id=connector.id)
        db.add(ss)
    else:
        ss.llm_default_connector_id = connector.id
    db.commit()


def _make_org_default(db, username: str) -> LlmConnector:
    """Create an admin-owned org connector and wire it as the system default."""
    owner = User(
        username=username,
        password_hash=get_password_hash("password123"),
        role="admin",
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)
    connector = _make_connector(db, owner, display_name="org-default")
    _wire_system_default(db, connector)
    return connector


@pytest.mark.asyncio
async def test_fallback_org_default_on_rate_limit(db, dj_user):
    """429 on DJ connector → falls back to org default → audit event written."""
    from app.models.llm_connector import LlmAuditEvent

    _make_connector(db, dj_user, display_name="dj-primary")

    org_connector = _make_org_default(db, "orgowner")

    fallback_response = ChatResponse(
        text="from-fallback",
        tool_calls=[],
        stop_reason="end_turn",
        usage=TokenUsage(prompt=3, completion=4),
    )

    # First call (DJ connector) → 429; second call (org default) → success.
    chat_mock = AsyncMock(
        side_effect=[RateLimited("slow", retry_after_seconds=5), fallback_response]
    )
    with _patch_chat(chat_mock):
        req = ChatRequest(
            messages=[Message(role="user", content="hi")],
            fallback_policy="org_default",
        )
        resp = await Gateway.dispatch(db, dj_user, req, purpose="test")

    assert resp.text == "from-fallback"
    assert chat_mock.await_count == 2

    # A fallback_triggered audit event referencing the fallback connector + trigger.
    audit = (
        db.query(LlmAuditEvent).filter(LlmAuditEvent.event_type.like("fallback_triggered%")).one()
    )
    assert audit.event_type == "fallback_triggered:rate_limited"
    assert audit.target_connector_id == org_connector.id
    assert audit.actor_user_id == dj_user.id


@pytest.mark.asyncio
async def test_fallback_none_surfaces_original_error(db, dj_user):
    """fallback_policy='none' (default) surfaces the original error, no fallback."""
    from app.models.llm_connector import LlmAuditEvent

    _make_connector(db, dj_user, display_name="dj-primary")

    _make_org_default(db, "orgowner2")

    chat_mock = AsyncMock(side_effect=RateLimited("slow", retry_after_seconds=5))
    with _patch_chat(chat_mock):
        req = ChatRequest(
            messages=[Message(role="user", content="hi")],
            fallback_policy="none",
        )
        with pytest.raises(RateLimited):
            await Gateway.dispatch(db, dj_user, req, purpose="test")

    # Only one attempt — no fallback.
    assert chat_mock.await_count == 1
    assert (
        db.query(LlmAuditEvent).filter(LlmAuditEvent.event_type.like("fallback_triggered%")).count()
        == 0
    )


@pytest.mark.asyncio
async def test_fallback_org_default_when_no_default_reraises(db, dj_user):
    """org_default policy with no org default configured → original error surfaces."""
    _make_connector(db, dj_user, display_name="dj-primary")

    chat_mock = AsyncMock(side_effect=ProviderUnavailable("down"))
    with _patch_chat(chat_mock):
        req = ChatRequest(
            messages=[Message(role="user", content="hi")],
            fallback_policy="org_default",
        )
        with pytest.raises(ProviderUnavailable):
            await Gateway.dispatch(db, dj_user, req, purpose="test")

    assert chat_mock.await_count == 1


@pytest.mark.asyncio
async def test_fallback_skipped_when_primary_is_org_default(db, dj_user):
    """If the failing connector IS the org default, there is nothing to fall back to."""
    dj_connector = _make_connector(db, dj_user, display_name="dj-and-org-default")
    _wire_system_default(db, dj_connector)

    chat_mock = AsyncMock(side_effect=RateLimited("slow"))
    with _patch_chat(chat_mock):
        req = ChatRequest(
            messages=[Message(role="user", content="hi")],
            fallback_policy="org_default",
        )
        with pytest.raises(RateLimited):
            await Gateway.dispatch(db, dj_user, req, purpose="test")

    assert chat_mock.await_count == 1


@pytest.mark.asyncio
async def test_retry_then_org_default_retries_same_then_falls_back(db, dj_user):
    """retry_then_org_default: same connector retried once, then org default."""
    _make_connector(db, dj_user, display_name="dj-primary")

    _make_org_default(db, "orgowner3")

    ok = ChatResponse(text="recovered", tool_calls=[], stop_reason="end_turn", usage=None)
    # attempt 1 (primary) 429, attempt 2 (primary retry) 429, attempt 3 (org default) ok
    chat_mock = AsyncMock(side_effect=[RateLimited("slow"), RateLimited("slow"), ok])
    with _patch_chat(chat_mock):
        req = ChatRequest(
            messages=[Message(role="user", content="hi")],
            fallback_policy="retry_then_org_default",
        )
        resp = await Gateway.dispatch(db, dj_user, req, purpose="test")

    assert resp.text == "recovered"
    # Bounded: exactly 3 attempts (1 primary + 1 retry + 1 fallback). Never loops.
    assert chat_mock.await_count == 3


@pytest.mark.asyncio
async def test_retry_then_org_default_succeeds_on_retry(db, dj_user):
    """retry_then_org_default: same-connector retry succeeds → no fallback needed."""
    _make_connector(db, dj_user, display_name="dj-primary")

    ok = ChatResponse(text="retry-ok", tool_calls=[], stop_reason="end_turn", usage=None)
    chat_mock = AsyncMock(side_effect=[ProviderUnavailable("blip"), ok])
    with _patch_chat(chat_mock):
        req = ChatRequest(
            messages=[Message(role="user", content="hi")],
            fallback_policy="retry_then_org_default",
        )
        resp = await Gateway.dispatch(db, dj_user, req, purpose="test")

    assert resp.text == "retry-ok"
    assert chat_mock.await_count == 2


@pytest.mark.asyncio
async def test_fallback_not_triggered_for_auth_invalid_when_policy_org_default(db, dj_user):
    """auth_invalid is fallback-eligible: marks primary invalid, falls back."""
    from app.models.llm_connector import LlmAuditEvent

    dj_connector = _make_connector(db, dj_user, display_name="dj-primary")

    org_connector = _make_org_default(db, "orgowner4")

    ok = ChatResponse(text="recovered", tool_calls=[], stop_reason="end_turn", usage=None)
    chat_mock = AsyncMock(side_effect=[AuthInvalid("expired"), ok])
    with _patch_chat(chat_mock):
        req = ChatRequest(
            messages=[Message(role="user", content="hi")],
            fallback_policy="org_default",
        )
        resp = await Gateway.dispatch(db, dj_user, req, purpose="test")

    assert resp.text == "recovered"
    # Primary connector marked auth_invalid; fallback audit + the auth_invalid audit both present.
    db.refresh(dj_connector)
    assert dj_connector.status == "auth_invalid"
    fallback_audit = (
        db.query(LlmAuditEvent)
        .filter(LlmAuditEvent.event_type == "fallback_triggered:auth_invalid")
        .one()
    )
    assert fallback_audit.target_connector_id == org_connector.id


@pytest.mark.asyncio
async def test_fallback_not_eligible_for_tool_translation_error(db, dj_user):
    """ToolTranslationError is NOT fallback-eligible — a different connector won't help."""
    from app.services.llm.exceptions import ToolTranslationError

    _make_connector(db, dj_user, display_name="dj-primary")

    _make_org_default(db, "orgowner5")

    chat_mock = AsyncMock(side_effect=ToolTranslationError("bad schema"))
    with _patch_chat(chat_mock):
        req = ChatRequest(
            messages=[Message(role="user", content="hi")],
            fallback_policy="retry_then_org_default",
        )
        with pytest.raises(ToolTranslationError):
            await Gateway.dispatch(db, dj_user, req, purpose="test")

    assert chat_mock.await_count == 1


@pytest.mark.asyncio
async def test_fallback_failure_surfaces_fallback_error(db, dj_user):
    """If the fallback connector also fails, the fallback's error surfaces."""
    _make_connector(db, dj_user, display_name="dj-primary")

    _make_org_default(db, "orgowner6")

    chat_mock = AsyncMock(
        side_effect=[RateLimited("primary-slow"), ProviderUnavailable("fallback-down")]
    )
    with _patch_chat(chat_mock):
        req = ChatRequest(
            messages=[Message(role="user", content="hi")],
            fallback_policy="org_default",
        )
        with pytest.raises(ProviderUnavailable):
            await Gateway.dispatch(db, dj_user, req, purpose="test")

    # primary + fallback, bounded.
    assert chat_mock.await_count == 2


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

    chat_mock = AsyncMock(return_value=fake_response)
    with _patch_chat(chat_mock):
        await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")

    chat_mock.assert_awaited_once()
    # Make sure the newer one was chosen
    db.refresh(newer)
    db.refresh(older)
    assert newer.last_used_at is not None
    # older.last_used_at was never set so should still be None
    assert older.last_used_at is None
