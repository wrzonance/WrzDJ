"""Shared connector health-check helper.

Used by:
- ``POST /api/llm/connectors/{id}/test`` (DJ-triggered manual test)
- ``connector_health_monitor`` background task (issue #340)

Every invocation:
1. Stamps ``last_health_check_at = utcnow()`` and the outcome on
   ``last_health_check_status`` (see :data:`HEALTH_CHECK_*` constants).
2. On auth failure, flips ``status`` to ``auth_invalid`` and writes a
   ``connector_health_check_failed`` audit row alongside the existing
   ``connector_health_check`` audit row.
3. Never raises — always returns the outcome. The caller decides whether to
   surface the error.

The helper does NOT commit. The caller owns the transaction so it can roll
back or combine with other writes (e.g. the background loop commits in a
single transaction per connector).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.llm_connector import (
    AUDIT_AUTH_INVALID_OBSERVED,
    AUDIT_HEALTH_CHECK,
    AUDIT_HEALTH_CHECK_FAILED,
    HEALTH_CHECK_AUTH_INVALID,
    HEALTH_CHECK_ERROR,
    HEALTH_CHECK_OK,
    HEALTH_CHECK_PROVIDER_UNAVAILABLE,
    HEALTH_CHECK_QUOTA_EXCEEDED,
    HEALTH_CHECK_RATE_LIMITED,
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    STATUS_DISABLED,
    LlmConnector,
)
from app.schemas.llm import ConnectorTestResult
from app.services.llm.connector_storage import audit_event
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
)
from app.services.llm.registry import get_adapter_class

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HealthCheckOutcome:
    """Result of a single connector health-check invocation."""

    ok: bool
    status: str
    """One of the HEALTH_CHECK_* constants."""
    error_code: str | None = None
    """Sanitised provider-class label; never includes a credential or upstream body."""
    status_flipped_to_auth_invalid: bool = False
    """True iff this call flipped the connector from ``active`` to ``auth_invalid``.

    The background monitor uses this to decide whether to notify the DJ —
    sending a notification on every periodic check would be noisy when the
    connector was already broken on the prior pass.
    """


async def run_health_check(
    db: Session,
    connector: LlmConnector,
    *,
    actor_user_id: int | None,
) -> HealthCheckOutcome:
    """Run ``adapter.health_check()`` against ``connector`` and record the outcome.

    ``actor_user_id`` may be ``None``: the background monitor passes
    ``connector.user_id``, which is NULL for org-scoped rows — those audit
    rows are recorded as system events (no attributable user).

    Writes (caller commits):
    - ``connector.last_health_check_at`` (always)
    - ``connector.last_health_check_status`` (always)
    - One ``llm_audit_event`` row of type ``connector_health_check`` (always)
    - If auth failed: flips ``connector.status`` to ``auth_invalid`` (unless
      already disabled), sets ``last_error``, and writes a second audit row
      of type ``auth_invalid_observed``.
    - If the auth failure was a transition (was active, now auth_invalid),
      writes a third ``connector_health_check_failed`` audit row so admins can
      filter on "the moment this connector broke".

    Never raises.
    """
    # Always write the AUDIT_HEALTH_CHECK row before the call so we have a
    # record even if the worker crashes mid-flight.
    audit_event(
        db,
        actor_user_id=actor_user_id,
        target_connector_id=connector.id,
        event_type=AUDIT_HEALTH_CHECK,
    )

    adapter_cls = get_adapter_class(connector.connector_type)
    adapter = adapter_cls(connector)

    now = utcnow()
    connector.last_health_check_at = now

    was_active = connector.status == STATUS_ACTIVE

    try:
        await adapter.health_check()
    except AuthInvalid:
        connector.last_health_check_status = HEALTH_CHECK_AUTH_INVALID
        flipped = False
        if connector.status != STATUS_DISABLED:
            if was_active:
                flipped = True
            connector.status = STATUS_AUTH_INVALID
            connector.last_error = "auth_invalid"
        audit_event(
            db,
            actor_user_id=actor_user_id,
            target_connector_id=connector.id,
            event_type=AUDIT_AUTH_INVALID_OBSERVED,
        )
        if flipped:
            # Distinct event so admins can filter "monitor caught a break"
            # separately from the "every check fires AUDIT_HEALTH_CHECK" noise.
            audit_event(
                db,
                actor_user_id=actor_user_id,
                target_connector_id=connector.id,
                event_type=AUDIT_HEALTH_CHECK_FAILED,
            )
        return HealthCheckOutcome(
            ok=False,
            status=HEALTH_CHECK_AUTH_INVALID,
            error_code="auth_invalid",
            status_flipped_to_auth_invalid=flipped,
        )
    except RateLimited:
        # Transient — don't flip status. Record the outcome and move on.
        connector.last_health_check_status = HEALTH_CHECK_RATE_LIMITED
        return HealthCheckOutcome(
            ok=False, status=HEALTH_CHECK_RATE_LIMITED, error_code="rate_limited"
        )
    except QuotaExceeded:
        connector.last_health_check_status = HEALTH_CHECK_QUOTA_EXCEEDED
        return HealthCheckOutcome(
            ok=False, status=HEALTH_CHECK_QUOTA_EXCEEDED, error_code="quota_exceeded"
        )
    except ProviderUnavailable:
        connector.last_health_check_status = HEALTH_CHECK_PROVIDER_UNAVAILABLE
        return HealthCheckOutcome(
            ok=False,
            status=HEALTH_CHECK_PROVIDER_UNAVAILABLE,
            error_code="provider_unavailable",
        )
    except Exception:  # noqa: BLE001 — adapter contract is broad; sanitised below
        # Don't leak the upstream exception text — it may include API keys.
        logger.exception("Connector health check failed unexpectedly")
        connector.last_health_check_status = HEALTH_CHECK_ERROR
        return HealthCheckOutcome(ok=False, status=HEALTH_CHECK_ERROR, error_code="unknown")

    # Success path
    connector.last_health_check_status = HEALTH_CHECK_OK
    connector.last_error = None
    # Clear auth_invalid on a successful check (mirrors test_connector behavior).
    if connector.status == STATUS_AUTH_INVALID:
        connector.status = STATUS_ACTIVE
    return HealthCheckOutcome(ok=True, status=HEALTH_CHECK_OK)


# Sanitised status → message mapping shared by every connector test endpoint.
# The health-check helper has already stripped any upstream payload from the
# outcome, so these fixed strings are all a client ever sees.
_HEALTH_CHECK_MESSAGES = {
    HEALTH_CHECK_AUTH_INVALID: "Authentication failed against the provider",
    HEALTH_CHECK_RATE_LIMITED: "Provider rate limited the request",
    HEALTH_CHECK_QUOTA_EXCEEDED: "Provider quota or billing failure",
    HEALTH_CHECK_PROVIDER_UNAVAILABLE: "Provider unreachable or timed out",
    HEALTH_CHECK_ERROR: "Unknown error",
}


def outcome_to_test_result(outcome: HealthCheckOutcome) -> ConnectorTestResult:
    """Sanitised DJ/admin-facing test result for a health-check outcome.

    Single source for the status → message mapping so the DJ test endpoint
    (``POST /api/llm/connectors/{id}/test``) and the admin org-connector test
    endpoint (``POST /api/admin/llm/org-connectors/{id}/test``) can never drift.
    """
    if outcome.ok:
        return ConnectorTestResult(ok=True)
    return ConnectorTestResult(
        ok=False,
        error_code=outcome.error_code or outcome.status,
        message=_HEALTH_CHECK_MESSAGES.get(outcome.status, "Unknown error"),
    )
