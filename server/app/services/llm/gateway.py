"""Gateway entrypoint — resolves a connector and dispatches to the adapter.

See spec §4.3.

Resolution order:
1. If ``actor`` is not ``None``:
   a. The DJ's explicit default active connector if one is pinned
      (``LlmConnector.is_default = True``) — issue #336.
   b. Else: most-recently-used active connector for the DJ.
2. Else: ``SystemSettings.llm_default_connector_id`` if set and active.
3. Else: raise :class:`NoLlmConfigured`.

Auto-fallback (issue #338):
When ``ChatRequest.fallback_policy`` is not ``"none"`` and the resolved
connector fails with a transient / credential error (rate-limited, auth
expired, provider unavailable, quota exceeded), the gateway optionally falls
back to the org-default connector. Retries are explicitly bounded — at most one
same-connector retry (for ``retry_then_org_default``) plus one org-default
attempt; the chain never loops.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from time import monotonic

from sqlalchemy import desc, nulls_last
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.llm_connector import (
    AUDIT_AUTH_INVALID_OBSERVED,
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    LlmConnector,
)
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.services.llm.base import ChatRequest, ChatResponse, ChatResponseChunk
from app.services.llm.connector_storage import audit_event, log_call
from app.services.llm.exceptions import (
    AuthInvalid,
    LlmError,
    NoLlmConfigured,
    ProviderUnavailable,
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
        primary = _resolve_connector(db, actor)
        actor_id = actor.id if actor else _system_actor_id(db, primary)

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
            fallback = _resolve_org_default(db)
            if fallback is None or fallback.id == primary.id:
                # No distinct org default to fall back to — surface the original.
                raise

            logger.info(
                "llm fallback: primary connector %s failed (%s); "
                "falling back to org-default connector %s",
                primary.id,
                trigger,
                fallback.id,
            )
            # Record the fallback before attempting it, referencing the fallback
            # connector + the trigger. Reuses the existing audit-write path.
            audit_event(
                db,
                actor_user_id=actor_id,
                target_connector_id=fallback.id,
                event_type=f"{AUDIT_FALLBACK_TRIGGERED}:{trigger}",
            )
            db.commit()
            # A failure here surfaces the fallback's own error (no further retry).
            return await _attempt(db, fallback, request, purpose=purpose, actor_id=actor_id)

    @staticmethod
    async def stream(
        db: Session,
        actor: User | None,
        request: ChatRequest,
        *,
        purpose: str,
    ) -> AsyncIterator[ChatResponseChunk]:
        """Stream a chat response, mirroring ``dispatch`` resolution + logging.

        Connector resolution is identical to ``dispatch`` (per-DJ default → MRU →
        org default). Logging differs only in timing: a single counts-only
        ``llm_call_log`` row is written when the stream finishes (success),
        errors, or is cancelled by the consumer. Consumer cancellation (e.g. an
        SSE client disconnect closing the generator) raises ``GeneratorExit``
        into ``_attempt_stream``, whose ``finally`` writes the log and lets the
        adapter's own ``async with`` cleanup close the upstream connection.

        Auto-fallback (``ChatRequest.fallback_policy``) is intentionally NOT
        applied to streaming: chunks have already been delivered to the consumer
        by the time a mid-stream error surfaces, so transparently restarting on
        another connector would corrupt the output. Streaming always fails fast.
        """
        primary = _resolve_connector(db, actor)
        actor_id = actor.id if actor else _system_actor_id(db, primary)
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
    actor_id: int,
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
        connector.status = STATUS_AUTH_INVALID
        connector.last_error = "auth_invalid"
        db.commit()
        log_call(
            db,
            connector_id=connector.id,
            purpose=purpose,
            status="auth_invalid",
            latency_ms=int((monotonic() - started) * 1000),
            error_code="401",
        )
        audit_event(
            db,
            actor_user_id=actor_id,
            target_connector_id=connector.id,
            event_type=AUDIT_AUTH_INVALID_OBSERVED,
        )
        db.commit()
        raise
    except RateLimited as exc:
        log_call(
            db,
            connector_id=connector.id,
            purpose=purpose,
            status="rate_limited",
            latency_ms=int((monotonic() - started) * 1000),
            error_code=str(exc.retry_after_seconds or ""),
        )
        db.commit()
        raise
    except QuotaExceeded:
        log_call(
            db,
            connector_id=connector.id,
            purpose=purpose,
            status="quota_exceeded",
            latency_ms=int((monotonic() - started) * 1000),
            error_code="402",
        )
        db.commit()
        raise
    except ProviderUnavailable as exc:
        log_call(
            db,
            connector_id=connector.id,
            purpose=purpose,
            status="provider_unavailable",
            latency_ms=int((monotonic() - started) * 1000),
            error_code=type(exc).__name__,
        )
        db.commit()
        raise
    except ToolTranslationError:
        log_call(
            db,
            connector_id=connector.id,
            purpose=purpose,
            status="tool_translation_error",
            latency_ms=int((monotonic() - started) * 1000),
            error_code="translation",
        )
        db.commit()
        raise
    except LlmError:
        log_call(
            db,
            connector_id=connector.id,
            purpose=purpose,
            status="error",
            latency_ms=int((monotonic() - started) * 1000),
            error_code="llm_error",
        )
        db.commit()
        raise

    # success path
    connector.last_used_at = utcnow()
    connector.last_error = None
    latency_ms = int((monotonic() - started) * 1000)
    tokens_in = response.usage.prompt if response.usage else None
    tokens_out = response.usage.completion if response.usage else None
    log_call(
        db,
        connector_id=connector.id,
        purpose=purpose,
        status="ok",
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    db.commit()
    return response


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
    fired; token counts come only from a terminal chunk's ``usage`` (never
    prompt/completion content). Auth failures additionally mark the connector
    ``auth_invalid`` and write an audit row, mirroring the non-stream ``_attempt``.
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
        # adapter's own context-manager cleanup closes the upstream connection.
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


def _resolve_connector(db: Session, actor: User | None) -> LlmConnector:
    if actor is not None:
        # Per-DJ explicit default takes precedence over MRU (issue #336).
        # Falls through to MRU if the DJ hasn't pinned a default or the pinned
        # connector is no longer active (so DJs aren't silently broken when
        # their default's status flips to ``auth_invalid`` / ``disabled``).
        pinned = (
            db.query(LlmConnector)
            .filter(
                LlmConnector.user_id == actor.id,
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
                LlmConnector.status == STATUS_ACTIVE,
            )
            .order_by(nulls_last(desc(LlmConnector.last_used_at)), desc(LlmConnector.id))
            .first()
        )
        if row is not None:
            return row

    default = _resolve_org_default(db)
    if default is not None:
        return default

    raise NoLlmConfigured("No active LLM connector for this DJ and no system default configured")


def _resolve_org_default(db: Session) -> LlmConnector | None:
    """Return the active org-default connector, or ``None`` if unset/inactive."""
    settings = db.query(SystemSettings).first()
    if settings and settings.llm_default_connector_id:
        default = db.get(LlmConnector, settings.llm_default_connector_id)
        if default is not None and default.status == STATUS_ACTIVE:
            return default
    return None


def _system_actor_id(db: Session, connector: LlmConnector) -> int:
    """Best-effort actor id for system-context audit rows.

    When the gateway is called with ``actor=None`` (system context), audit
    events should still record an actor; fall back to the connector's owner so
    the trail is traceable.
    """
    return connector.user_id
