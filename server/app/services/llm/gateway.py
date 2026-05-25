"""Gateway entrypoint — resolves a connector and dispatches to the adapter.

See spec §4.3.

Resolution order:
1. If ``actor`` is not ``None``: most-recently-used active connector for the DJ.
2. Else: ``SystemSettings.llm_default_connector_id`` if set and active.
3. Else: raise :class:`NoLlmConfigured`.
"""

from __future__ import annotations

import logging
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
from app.services.llm.base import ChatRequest, ChatResponse
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
        connector = _resolve_connector(db, actor)
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
                actor_user_id=actor.id if actor else _system_actor_id(db, connector),
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


def _resolve_connector(db: Session, actor: User | None) -> LlmConnector:
    if actor is not None:
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

    settings = db.query(SystemSettings).first()
    if settings and settings.llm_default_connector_id:
        default = db.get(LlmConnector, settings.llm_default_connector_id)
        if default is not None and default.status == STATUS_ACTIVE:
            return default

    raise NoLlmConfigured("No active LLM connector for this DJ and no system default configured")


def _system_actor_id(db: Session, connector: LlmConnector) -> int:
    """Best-effort actor id for system-context audit rows.

    When the gateway is called with ``actor=None`` (system context), audit
    events should still record an actor; fall back to the connector's owner so
    the trail is traceable.
    """
    return connector.user_id
