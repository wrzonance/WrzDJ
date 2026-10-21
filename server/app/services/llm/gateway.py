"""Gateway entrypoint — resolves a connector and dispatches to the adapter.

See spec §4.3.

Resolution order:
1. If ``actor`` is not ``None`` — the per-DJ chain, which only ever returns
   ``scope='user'`` rows:
   a. The DJ's per-feature pin for ``purpose`` if set and the pinned connector
      is active (``LlmFeaturePreference`` — issue #337). Skipped gracefully when
      the pinned connector was deleted or is no longer active.
   b. Else: the DJ's explicit default active connector if one is pinned
      (``LlmConnector.is_default = True``) — issue #336.
   c. Else: most-recently-used active connector for the DJ.
2. Else (no actor, or no per-DJ match): the org fallback —
   ``SystemSettings.llm_default_connector_id`` when it points at an ACTIVE
   ``scope='org'`` row AND ``SystemSettings.llm_enabled`` is True.
   ``llm_enabled`` gates ONLY this fallback; a DJ's own connector is never
   blocked by it.
3. Else: raise :class:`NoLlmConfigured`.

System-context calls (``actor=None``) record a NULL actor on audit rows rather
than misattributing usage to the connector's owner.

Auto-fallback (issue #338):
When ``ChatRequest.fallback_policy`` is not ``"none"`` and the resolved
connector fails with a transient / credential error (rate-limited, auth
expired, provider unavailable, quota exceeded), the gateway optionally falls
back to the org-default connector. Retries are explicitly bounded — at most one
same-connector retry (for ``retry_then_org_default``) plus one org-default
attempt; the chain never loops.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from time import monotonic

from sqlalchemy import desc, nulls_last
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.llm_connector import (
    AUDIT_AUTH_INVALID_OBSERVED,
    SCOPE_ORG,
    SCOPE_USER,
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    LlmConnector,
)
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.services.llm.base import ChatRequest, ChatResponse, ChatResponseChunk
from app.services.llm.connector_preferences import get_feature_preference
from app.services.llm.connector_telemetry import audit_event, current_month_token_usage, log_call
from app.services.llm.exceptions import (
    AuthInvalid,
    LlmError,
    NoLlmConfigured,
    ProviderUnavailable,
    QuotaCapReached,
    QuotaExceeded,
    RateLimited,
    ToolTranslationError,
)
from app.services.llm.registry import get_adapter_class

logger = logging.getLogger(__name__)

# Audit event type prefix for auto-fallback. The trigger reason is appended
# (e.g. ``fallback_triggered:rate_limited``) so it fits the existing
# ``llm_audit_event.event_type`` String(60) column without a migration. The
# audit row's ``target_connector_id`` points at the fallback connector.
AUDIT_FALLBACK_TRIGGERED = "fallback_triggered"

# Maps fallback-eligible exception types → the trigger token recorded in the
# audit event. Errors NOT in this map (ToolTranslationError, generic LlmError)
# are never fallback-eligible: a different connector would hit the same problem.
_FALLBACK_TRIGGERS: dict[type[LlmError], str] = {
    RateLimited: "rate_limited",
    AuthInvalid: "auth_invalid",
    ProviderUnavailable: "provider_unavailable",
    QuotaExceeded: "quota_exceeded",
}


def _fallback_trigger(exc: LlmError) -> str | None:
    """Return the trigger token for a fallback-eligible error, else ``None``."""
    for exc_type, token in _FALLBACK_TRIGGERS.items():
        if isinstance(exc, exc_type):
            return token
    return None


def _gateway_session(db: Session) -> Session:
    """Create a gateway-owned persistence session on the caller's bind.

    Engine-bound callers receive an independent connection and transaction.
    When a caller is explicitly bound to an existing Connection (as in an
    externally managed transaction), rollback-only joining prevents gateway
    commits from taking ownership of that transaction.
    """
    return Session(bind=db.get_bind(), join_transaction_mode="rollback_only")


def _record_call_outcome(
    db: Session,
    *,
    connector_id: int,
    purpose: str,
    started: float,
    status: str,
    error_code: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    actor_id: int | None = None,
    audit_event_type: str | None = None,
    last_used: bool = False,
    auth_invalid: bool = False,
) -> None:
    """Persist gateway-owned connector state and call telemetry atomically."""
    with _gateway_session(db) as telemetry_db:
        connector = telemetry_db.get(LlmConnector, connector_id)
        if connector is not None:
            if last_used:
                connector.last_used_at = utcnow()
                connector.last_error = None
            if auth_invalid:
                connector.status = STATUS_AUTH_INVALID
                connector.last_error = "auth_invalid"

        log_call(
            telemetry_db,
            connector_id=connector_id,
            purpose=purpose,
            status=status,
            latency_ms=int((monotonic() - started) * 1000),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error_code=error_code,
        )
        if audit_event_type is not None:
            audit_event(
                telemetry_db,
                actor_user_id=actor_id,
                target_connector_id=connector_id,
                event_type=audit_event_type,
            )
        telemetry_db.commit()


def _record_audit_event(
    db: Session,
    *,
    actor_id: int | None,
    connector_id: int,
    event_type: str,
) -> None:
    """Persist an audit event without committing the caller-owned session."""
    with _gateway_session(db) as telemetry_db:
        audit_event(
            telemetry_db,
            actor_user_id=actor_id,
            target_connector_id=connector_id,
            event_type=event_type,
        )
        telemetry_db.commit()


def _record_failure(
    db: Session,
    connector: LlmConnector,
    *,
    purpose: str,
    started: float,
    status: str,
    error_code: str,
) -> None:
    """Persist failed-call telemetry before the original typed error is re-raised."""
    _record_call_outcome(
        db,
        connector_id=connector.id,
        purpose=purpose,
        started=started,
        status=status,
        error_code=error_code,
    )


def _enforce_monthly_cap(db: Session, connector: LlmConnector) -> None:
    """Pre-flight: refuse dispatch when the connector's monthly cap is reached.

    No-op when the connector has no cap (``monthly_token_cap is None``).
    Compares the current calendar month's summed token usage against the cap;
    refuses when usage already meets or exceeds it. Raised BEFORE any provider
    call, so no tokens are spent and editing the cap never disrupts an
    already-dispatched (in-flight) call (issue #339).

    The error message is fixed and leaks no internals (usage totals, cap value,
    connector id) — see the issue's security note.
    """
    cap = connector.monthly_token_cap
    if cap is None:
        return
    used = current_month_token_usage(db, connector.id)
    if used >= cap:
        raise QuotaCapReached("Your monthly token cap is reached. Contact your admin to raise it.")


class Gateway:
    """Single dispatch entrypoint."""

    @staticmethod
    async def dispatch(
        db: Session,
        actor: User | None,
        request: ChatRequest,
        *,
        purpose: str,
    ) -> ChatResponse:
        primary = _resolve_connector(db, actor, purpose=purpose)
        # NULL actor = system-context call; audit rows record no user rather
        # than misattributing usage to the connector's owner.
        actor_id = actor.id if actor else None

        # Pre-flight: refuse if the resolved connector's monthly cap is reached
        # (issue #339). Raised before any provider call — no tokens spent, and
        # a cap edit never disrupts an in-flight call. QuotaCapReached is not in
        # _FALLBACK_TRIGGERS, so it short-circuits to the caller (a cap is not a
        # transient/credential error a different connector would dodge).
        _enforce_monthly_cap(db, primary)

        # Attempt 1: primary connector.
        try:
            return await _attempt(db, primary, request, purpose=purpose, actor_id=actor_id)
        except LlmError as exc:
            trigger = _fallback_trigger(exc)
            policy = request.fallback_policy
            if policy == "none" or trigger is None:
                raise

            # Attempt 2 (retry_then_org_default only): one bounded retry on the
            # SAME connector before falling back.
            if policy == "retry_then_org_default":
                try:
                    return await _attempt(db, primary, request, purpose=purpose, actor_id=actor_id)
                except LlmError as retry_exc:
                    retry_trigger = _fallback_trigger(retry_exc)
                    if retry_trigger is None:
                        raise
                    # Carry the retry's trigger forward to the fallback step.
                    exc, trigger = retry_exc, retry_trigger

            # Attempt 3: org-default fallback (one bounded attempt).
            fallback = resolve_org_default_connector(db)
            if fallback is None or fallback.id == primary.id:
                # No distinct org default to fall back to — surface the original.
                raise

            # The fallback connector may itself be capped — refuse rather than
            # silently spending another DJ's budget (issue #339).
            _enforce_monthly_cap(db, fallback)

            logger.info(
                "llm fallback: primary connector %s failed (%s); "
                "falling back to org-default connector %s",
                primary.id,
                trigger,
                fallback.id,
            )
            # Record the fallback before attempting it, referencing the fallback
            # connector + the trigger. Reuses the existing audit-write path.
            _record_audit_event(
                db,
                actor_id=actor_id,
                connector_id=fallback.id,
                event_type=f"{AUDIT_FALLBACK_TRIGGERED}:{trigger}",
            )
            # A failure here surfaces the fallback's own error (no further retry).
            return await _attempt(db, fallback, request, purpose=purpose, actor_id=actor_id)

    @staticmethod
    async def stream(
        db: Session,
        actor: User | None,
        request: ChatRequest,
        *,
        purpose: str,
        connector_id: int | None = None,
    ) -> AsyncIterator[ChatResponseChunk]:
        """Stream a chat response, mirroring ``dispatch`` resolution + logging.

        Without ``connector_id``, resolution is identical to ``dispatch``
        (per-feature pin → per-DJ default → MRU → org default). A supplied ID
        selects exactly that active user-owned connector. Logging differs only
        in timing: a single counts-only ``llm_call_log`` row is written when
        the stream finishes (success), errors, or is cancelled by the consumer.
        Consumer cancellation (e.g. an SSE client disconnect closing the
        generator) raises ``GeneratorExit`` into ``_attempt_stream``, whose
        ``finally`` writes the log and lets the adapter's own ``async with``
        cleanup close the upstream connection.

        Auto-fallback (``ChatRequest.fallback_policy``) is intentionally NOT
        applied to streaming: chunks have already been delivered to the consumer
        by the time a mid-stream error surfaces, so transparently restarting on
        another connector would corrupt the output. Streaming always fails fast.
        """
        primary = _resolve_stream_connector(db, actor, purpose=purpose, connector_id=connector_id)
        _enforce_monthly_cap(db, primary)
        # NULL actor = system-context call; audit rows record no user rather
        # than misattributing usage to the connector's owner.
        actor_id = actor.id if actor else None
        inner = _attempt_stream(db, primary, request, purpose=purpose, actor_id=actor_id)
        try:
            async for chunk in inner:
                yield chunk
        finally:
            # Closing the outer generator (e.g. SSE client disconnect) must
            # synchronously close the inner one so ``_attempt_stream``'s finally
            # fires now — writing the call log + closing the upstream connection —
            # rather than waiting for garbage collection.
            await inner.aclose()


async def _attempt(
    db: Session,
    connector: LlmConnector,
    request: ChatRequest,
    *,
    purpose: str,
    actor_id: int | None,
) -> ChatResponse:
    """Run a single adapter call against ``connector``, logging the outcome.

    Raises the same typed exceptions the adapter raises after logging the call
    (and, for auth failures, marking the connector + writing an audit event).
    """
    adapter_cls = get_adapter_class(connector.connector_type)
    adapter = adapter_cls(connector)
    started = monotonic()
    try:
        response = await adapter.chat(request)
    except AuthInvalid:
        _record_call_outcome(
            db,
            connector_id=connector.id,
            purpose=purpose,
            started=started,
            status="auth_invalid",
            error_code="401",
            actor_id=actor_id,
            audit_event_type=AUDIT_AUTH_INVALID_OBSERVED,
            auth_invalid=True,
        )
        raise
    except RateLimited as exc:
        _record_failure(
            db,
            connector,
            purpose=purpose,
            status="rate_limited",
            error_code=str(exc.retry_after_seconds or ""),
            started=started,
        )
        raise
    except QuotaExceeded:
        _record_failure(
            db,
            connector,
            purpose=purpose,
            status="quota_exceeded",
            error_code="402",
            started=started,
        )
        raise
    except ProviderUnavailable as exc:
        _record_failure(
            db,
            connector,
            purpose=purpose,
            status="provider_unavailable",
            error_code=type(exc).__name__,
            started=started,
        )
        raise
    except ToolTranslationError:
        _record_failure(
            db,
            connector,
            purpose=purpose,
            status="tool_translation_error",
            error_code="translation",
            started=started,
        )
        raise
    except LlmError:
        _record_failure(
            db,
            connector,
            purpose=purpose,
            status="error",
            error_code="llm_error",
            started=started,
        )
        raise

    # success path
    tokens_in = response.usage.prompt if response.usage else None
    tokens_out = response.usage.completion if response.usage else None
    _record_call_outcome(
        db,
        connector_id=connector.id,
        purpose=purpose,
        started=started,
        status="ok",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        last_used=True,
    )
    # Surface which connector served the call (issue #391 — vibe provenance).
    return response.model_copy(update={"provider": connector.connector_type})


async def _attempt_stream(
    db: Session,
    connector: LlmConnector,
    request: ChatRequest,
    *,
    purpose: str,
    actor_id: int | None,
) -> AsyncGenerator[ChatResponseChunk, None]:
    """Run a single adapter stream, logging exactly one outcome row.

    The call log is written in a ``finally`` so it fires on success, on a typed
    error, AND on consumer cancellation (``GeneratorExit`` raised into the
    generator when the SSE client disconnects). The status reflects which path
    fired; token counts come only from a terminal chunk's ``usage`` (never
    prompt/completion content). Auth failures additionally mark the connector
    ``auth_invalid`` and write an audit row, mirroring the non-stream ``_attempt``.
    """
    started = monotonic()
    # Only a fully exhausted adapter stream is successful. Start in the failure
    # state so unexpected parser/provider exceptions cannot update last_used_at.
    status = "error"
    error_code: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    auth_failed = False

    try:
        adapter_cls = get_adapter_class(connector.connector_type)
        adapter = adapter_cls(connector)
        async for chunk in adapter.stream(request):
            if chunk.usage is not None:
                tokens_in = chunk.usage.prompt
                tokens_out = chunk.usage.completion
            yield chunk
        status = "ok"
    except GeneratorExit:
        # Consumer disconnected — record as cancelled and re-raise so the
        # adapter's own context-manager cleanup closes the upstream connection.
        status = "cancelled"
        error_code = "client_disconnect"
        raise
    except asyncio.CancelledError:
        # The serving task was cancelled while awaiting the provider stream.
        # Preserve partial usage, but never mark the connector as successfully used.
        status = "cancelled"
        error_code = "task_cancelled"
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
    except Exception as exc:
        # Record only the exception class. Provider errors may contain response
        # bodies, endpoint URLs, or other sensitive data in their message.
        status = "error"
        error_code = type(exc).__name__
        raise ProviderUnavailable("Upstream stream failed") from None
    finally:
        _record_call_outcome(
            db,
            connector_id=connector.id,
            purpose=purpose,
            started=started,
            status=status,
            tokens_in=tokens_in if status in {"ok", "cancelled"} else None,
            tokens_out=tokens_out if status in {"ok", "cancelled"} else None,
            error_code=error_code,
            actor_id=actor_id,
            audit_event_type=AUDIT_AUTH_INVALID_OBSERVED if auth_failed else None,
            last_used=status == "ok",
            auth_invalid=auth_failed,
        )


def _resolve_connector(db: Session, actor: User | None, *, purpose: str) -> LlmConnector:
    if actor is not None:
        # 0. Per-feature pin (issue #337) takes precedence over the per-DJ
        #    default and MRU. Skipped gracefully when the pinned connector was
        #    deleted (FK row gone) or is no longer active, so a stale/broken
        #    pin never silently breaks the DJ — resolution falls through to the
        #    per-DJ default / MRU / org-default chain below.
        pref = get_feature_preference(db, user_id=actor.id, feature=purpose)
        if pref is not None:
            pinned_feature = db.get(LlmConnector, pref.connector_id)
            if (
                pinned_feature is not None
                and pinned_feature.user_id == actor.id
                and pinned_feature.status == STATUS_ACTIVE
                and pinned_feature.scope == SCOPE_USER
            ):
                return pinned_feature

        # Per-DJ explicit default takes precedence over MRU (issue #336).
        # Falls through to MRU if the DJ hasn't pinned a default or the pinned
        # connector is no longer active (so DJs aren't silently broken when
        # their default's status flips to ``auth_invalid`` / ``disabled``).
        pinned = (
            db.query(LlmConnector)
            .filter(
                LlmConnector.user_id == actor.id,
                LlmConnector.scope == SCOPE_USER,
                LlmConnector.status == STATUS_ACTIVE,
                LlmConnector.is_default == True,  # noqa: E712 (SQLAlchemy comparison)
            )
            .first()
        )
        if pinned is not None:
            return pinned

        row = (
            db.query(LlmConnector)
            .filter(
                LlmConnector.user_id == actor.id,
                LlmConnector.scope == SCOPE_USER,
                LlmConnector.status == STATUS_ACTIVE,
            )
            .order_by(nulls_last(desc(LlmConnector.last_used_at)), desc(LlmConnector.id))
            .first()
        )
        if row is not None:
            return row

    default = resolve_org_default_connector(db)
    if default is not None:
        return default

    raise NoLlmConfigured("No active LLM connector for this DJ and no system default configured")


def _resolve_stream_connector(
    db: Session,
    actor: User | None,
    *,
    purpose: str,
    connector_id: int | None,
) -> LlmConnector:
    """Resolve a regular stream by policy or an explicitly requested owned connector."""
    if connector_id is None:
        return _resolve_connector(db, actor, purpose=purpose)

    connector = db.get(LlmConnector, connector_id)
    if (
        actor is None
        or connector is None
        or connector.user_id != actor.id
        or connector.scope != SCOPE_USER
        or connector.status != STATUS_ACTIVE
    ):
        raise NoLlmConfigured("The selected connector is unavailable")
    return connector


def resolve_org_default_connector(db: Session) -> LlmConnector | None:
    """Active org-scoped default, gated by the org-fallback policy toggle.

    ``llm_enabled`` governs ONLY this path: DJs with their own connector are
    resolved earlier and never reach here. Returns ``None`` when the toggle is
    off, no default is set, or the default is not an active org-scoped row.
    """
    settings = db.query(SystemSettings).first()
    if not settings or not settings.llm_enabled or not settings.llm_default_connector_id:
        return None
    default = db.get(LlmConnector, settings.llm_default_connector_id)
    if default is not None and default.scope == SCOPE_ORG and default.status == STATUS_ACTIVE:
        return default
    return None
