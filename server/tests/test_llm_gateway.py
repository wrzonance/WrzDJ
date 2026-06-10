"""Tests for the LLM gateway dispatch + connector resolution."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.models.llm_connector import SCOPE_ORG, LlmConnector
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
    user: User | None,
    *,
    connector_type: str = "openai_apikey",
    display_name: str = "Test connector",
    status: str = "active",
    model_hint: str = "gpt-5-mini",
    scope: str = "user",
) -> LlmConnector:
    """Insert a connector. Org-scoped rows (scope='org') take ``user=None``."""
    row = LlmConnector(
        user_id=user.id if user is not None else None,
        connector_type=connector_type,
        display_name=display_name,
        status=status,
        credentials=json.dumps({"api_key": "sk-fake-key"}),
        model_hint=model_hint,
        scope=scope,
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
async def test_falls_back_to_system_default(db, gateway_request):
    # No actor (system context) — falls back to the org-scoped system default.
    default_connector = _make_connector(
        db, None, scope=SCOPE_ORG, display_name="default-org-connector"
    )
    _wire_system_default(db, default_connector)

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


def _make_org_default(db) -> LlmConnector:
    """Create an org-scoped connector (user_id=NULL) wired as the system default.

    Only ACTIVE scope='org' rows serve as the org fallback now — a user-scoped
    row wired as the default never resolves (see TestOrgScopedResolution).
    """
    connector = _make_connector(db, None, scope=SCOPE_ORG, display_name="org-default")
    _wire_system_default(db, connector)
    return connector


@pytest.mark.asyncio
async def test_fallback_org_default_on_rate_limit(db, dj_user):
    """429 on DJ connector → falls back to org default → audit event written."""
    from app.models.llm_connector import LlmAuditEvent

    _make_connector(db, dj_user, display_name="dj-primary")

    org_connector = _make_org_default(db)

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

    _make_org_default(db)

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

    _make_org_default(db)

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

    org_connector = _make_org_default(db)

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

    _make_org_default(db)

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

    _make_org_default(db)

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


# ---------- org-scoped resolution + llm_enabled policy ----------


def _set_llm_enabled(db, enabled: bool) -> None:
    ss = db.query(SystemSettings).first()
    if ss is None:
        ss = SystemSettings(id=1)
        db.add(ss)
    ss.llm_enabled = enabled
    db.commit()


def _ok_response(text: str = "ok") -> ChatResponse:
    return ChatResponse(text=text, tool_calls=[], stop_reason="end_turn", usage=None)


class TestOrgScopedResolution:
    """Scope-filtered resolution and the ``llm_enabled`` org-fallback policy.

    ``llm_enabled`` now means exactly "org fallback allowed": a DJ's own
    (user-scoped) connector always dispatches regardless of the toggle, while
    connector-less DJs and system-context calls reach the org default only when
    it is an ACTIVE scope='org' row AND the toggle is on.
    """

    # HEADLINE REGRESSION: a DJ's own connector is never blocked by llm_enabled.
    @pytest.mark.asyncio
    async def test_byo_dj_dispatch_works_with_llm_enabled_false(self, db, dj_user, gateway_request):
        connector = _make_connector(db, dj_user)
        _set_llm_enabled(db, False)

        with _patch_chat(AsyncMock(return_value=_ok_response())):
            resp = await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")

        assert resp.text == "ok"
        db.refresh(connector)
        assert connector.last_used_at is not None

    @pytest.mark.asyncio
    async def test_connectorless_dj_blocked_when_llm_enabled_false(
        self, db, dj_user, gateway_request
    ):
        """llm_enabled=False blocks the org fallback for connector-less DJs."""
        org = _make_connector(db, None, scope=SCOPE_ORG, display_name="org-row")
        _wire_system_default(db, org)
        _set_llm_enabled(db, False)

        chat_mock = AsyncMock(return_value=_ok_response())
        with _patch_chat(chat_mock):
            with pytest.raises(NoLlmConfigured):
                await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")

        chat_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connectorless_dj_uses_org_fallback_when_enabled(
        self, db, dj_user, gateway_request
    ):
        org = _make_connector(db, None, scope=SCOPE_ORG, display_name="org-row")
        _wire_system_default(db, org)
        _set_llm_enabled(db, True)

        with _patch_chat(AsyncMock(return_value=_ok_response("from-org"))):
            resp = await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")

        assert resp.text == "from-org"
        db.refresh(org)
        assert org.last_used_at is not None

    @pytest.mark.asyncio
    async def test_user_scoped_default_never_resolves_as_org_fallback(
        self, db, dj_user, gateway_request
    ):
        """A user-scoped personal key wired as the system default must never
        serve the org fallback — even with llm_enabled=True."""
        from app.models.llm_connector import LlmAuditEvent

        personal = _make_connector(db, dj_user, display_name="personal-key")  # scope='user'
        _wire_system_default(db, personal)
        _set_llm_enabled(db, True)

        chat_mock = AsyncMock(return_value=_ok_response("leaked"))
        with _patch_chat(chat_mock):
            with pytest.raises(NoLlmConfigured):
                await Gateway.dispatch(db, None, gateway_request, purpose="test")

        chat_mock.assert_not_awaited()
        # Resolution failed before any call — no audit row may reference the
        # personal connector (the old code would have misattributed its owner).
        assert (
            db.query(LlmAuditEvent).filter(LlmAuditEvent.target_connector_id == personal.id).count()
            == 0
        )

    @pytest.mark.asyncio
    async def test_org_row_never_resolves_in_per_dj_chain(self, db, dj_user, gateway_request):
        """The per-DJ chain (pin → pinned default → MRU) returns scope='user'
        rows only: with the fallback blocked by llm_enabled=False, an active
        org row must not leak in via MRU."""
        org = _make_connector(db, None, scope=SCOPE_ORG, display_name="only-org")
        _wire_system_default(db, org)
        _set_llm_enabled(db, False)

        chat_mock = AsyncMock(return_value=_ok_response())
        with _patch_chat(chat_mock):
            with pytest.raises(NoLlmConfigured):
                await Gateway.dispatch(db, dj_user, gateway_request, purpose="test")

        chat_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_system_context_audit_actor_is_null_on_auth_failure(self, db, gateway_request):
        """System-context calls (actor=None) record a NULL audit actor — never
        a user id misattributed from the connector's owner."""
        from app.models.llm_connector import LlmAuditEvent

        org = _make_connector(db, None, scope=SCOPE_ORG, display_name="org-row")
        _wire_system_default(db, org)
        _set_llm_enabled(db, True)

        with _patch_chat(AsyncMock(side_effect=AuthInvalid("expired"))):
            with pytest.raises(AuthInvalid):
                await Gateway.dispatch(db, None, gateway_request, purpose="test")

        audit = (
            db.query(LlmAuditEvent)
            .filter(LlmAuditEvent.target_connector_id == org.id)
            .order_by(LlmAuditEvent.id.desc())
            .first()
        )
        assert audit is not None
        assert audit.event_type == "auth_invalid_observed"
        assert audit.actor_user_id is None
