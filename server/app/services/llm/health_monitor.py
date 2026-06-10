"""Background connector health monitor (issue #340).

Scheduled task that periodically runs ``health_check`` on every
``status="active"`` connector to catch expired / revoked credentials before
a DJ tries to use one mid-event.

Design:
- Loop wakes every ``HEALTH_MONITOR_SCAN_INTERVAL_SECONDS`` (5 min).
- For each active connector whose ``last_health_check_at`` is older than
  ``effective_interval_seconds(connector)`` ago, run a check.
- Per-connector jitter (±30%) staggers checks so a fleet of N connectors
  doesn't all hit one provider at once (avoid a thundering-herd 429).
- Sequential within a pass: one connector at a time, with a small sleep
  between calls, so we respect per-provider rate limits even when all DJs
  share a single upstream account.
- On a transition active → auth_invalid, notify the DJ:
    1. Email via Resend if configured AND the user has an email.
    2. Otherwise, log a warning.
  The flipped status itself is the in-app banner (the DJ's /settings/ai page
  surfaces ``status`` per connector, and the recommendation engine raises
  ``NoLlmConfigured`` when no active connector exists).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.llm_connector import STATUS_ACTIVE, LlmConnector
from app.models.user import User
from app.services.llm.health_check import HealthCheckOutcome, run_health_check

logger = logging.getLogger(__name__)

# Default check interval in hours; overridable via env var
# ``LLM_HEALTH_CHECK_INTERVAL_HOURS``. Six hours = four checks per day, which
# is well under any provider's per-key rate limit but still catches breakage
# inside a single working day.
_DEFAULT_INTERVAL_HOURS = 6
_HEALTH_CHECK_INTERVAL_HOURS_ENV = "LLM_HEALTH_CHECK_INTERVAL_HOURS"

# How often the loop wakes to look for due connectors. Shorter than the
# interval so jitter is smooth; the cost is one tiny SELECT per scan.
HEALTH_MONITOR_SCAN_INTERVAL_SECONDS = 300

# Sleep between consecutive health-check calls within a single scan pass.
# Spreads load across the upstream providers and limits the per-DJ impact of
# the monitor when many connectors are due at once.
_PER_CHECK_SLEEP_SECONDS = 1.0


def _get_interval_seconds() -> int:
    """Read the configured interval from the env, clamped to safe bounds.

    A non-positive or absurdly large value falls back to the default so a
    misconfigured ``.env`` can never disable the monitor or DoS providers.
    """
    raw = os.environ.get(_HEALTH_CHECK_INTERVAL_HOURS_ENV)
    if not raw:
        hours = _DEFAULT_INTERVAL_HOURS
    else:
        try:
            hours = int(raw)
        except ValueError:
            logger.warning(
                "Invalid %s=%r; falling back to %s",
                _HEALTH_CHECK_INTERVAL_HOURS_ENV,
                raw,
                _DEFAULT_INTERVAL_HOURS,
            )
            hours = _DEFAULT_INTERVAL_HOURS
    # Floor: 1 hour (faster = wastes upstream rate limit).
    # Ceiling: 168 hours / 7 days (slower = defeats the purpose).
    hours = max(1, min(168, hours))
    return hours * 3600


def _jitter_factor(connector_id: int) -> float:
    """Per-connector deterministic jitter in [0.7, 1.3].

    Deterministic-by-id so successive scans don't reshuffle the schedule on
    every wake (which would mean some connectors get hit far more often than
    intended). The hash spreads connectors uniformly across the 30% band.
    """
    # SHA-256 is overkill cryptographically, but it's already in the stdlib
    # and gives a clean uniform distribution. The first 4 bytes are plenty.
    h = hashlib.sha256(str(connector_id).encode("ascii")).digest()
    n = int.from_bytes(h[:4], "big")
    # Map [0, 2**32) → [0, 1)
    frac = n / float(1 << 32)
    # Map [0, 1) → [0.7, 1.3)
    return 0.7 + (frac * 0.6)


def effective_interval_seconds(connector: LlmConnector) -> int:
    """Effective check interval for ``connector`` (base × per-connector jitter)."""
    return int(_get_interval_seconds() * _jitter_factor(connector.id))


def _is_due(connector: LlmConnector) -> bool:
    """True iff ``connector`` is overdue for a periodic health check."""
    if connector.last_health_check_at is None:
        return True
    elapsed = (utcnow() - connector.last_health_check_at).total_seconds()
    return elapsed >= effective_interval_seconds(connector)


def _select_due_connectors(db: Session) -> list[LlmConnector]:
    """Return active connectors whose last check is older than their effective interval.

    Filtering ``status == STATUS_ACTIVE`` cheaply in SQL avoids reading
    disabled rows. The per-row jitter calculation is done in Python because
    SQLite (used in tests) lacks a stable hash function.
    """
    active = (
        db.query(LlmConnector)
        .filter(LlmConnector.status == STATUS_ACTIVE)
        .order_by(LlmConnector.last_health_check_at.asc().nulls_first())
        .all()
    )
    return [c for c in active if _is_due(c)]


def _notify_dj_auth_invalid(db: Session, connector: LlmConnector) -> None:
    """Best-effort email notification when the monitor flips a connector to auth_invalid.

    Channels tried (in order):
    1. Email via Resend, if the user has a non-empty ``email`` AND Resend is
       configured (the sender raises ``EmailNotConfiguredError`` otherwise).
    2. Logs at WARNING. The connector's flipped status itself surfaces in
       the DJ's settings UI on next login.

    Never raises — notification failures must not block subsequent health
    checks in the same pass.
    """
    try:
        user = db.get(User, connector.user_id)
    except Exception:  # noqa: BLE001 — defensive: DB hiccup must not kill the loop
        logger.exception("health monitor: failed to load user for connector %s", connector.id)
        user = None

    if user is None or not user.email:
        logger.warning(
            "health monitor: connector %s (user_id=%s) flipped to auth_invalid; "
            "no email on file — DJ will see the banner on next login.",
            connector.id,
            connector.user_id,
        )
        return

    try:
        from app.services.email_sender import (
            EmailNotConfiguredError,
            EmailSendError,
            send_connector_auth_invalid_notification,
        )

        send_connector_auth_invalid_notification(
            to_address=user.email,
            display_name=connector.display_name,
            connector_type=connector.connector_type,
        )
    except EmailNotConfiguredError:
        logger.warning(
            "health monitor: connector %s flipped to auth_invalid; "
            "email not configured — DJ will see the banner on next login.",
            connector.id,
        )
    except EmailSendError:
        logger.exception(
            "health monitor: failed to send auth_invalid email for connector %s",
            connector.id,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "health monitor: unexpected error notifying DJ of connector %s",
            connector.id,
        )


async def _check_one(db: Session, connector: LlmConnector) -> HealthCheckOutcome:
    """Run a health check on ``connector``, commit, and notify if it just broke.

    The audit row is written with ``actor_user_id = connector.user_id``
    because the periodic check is *on behalf of* the owning DJ (vs the manual
    test button, where the actor is whoever clicked it). For org-scoped rows
    ``connector.user_id`` is NULL, so their audit rows carry a NULL actor and
    surface as "system" events in the admin audit views.
    """
    outcome = await run_health_check(db, connector, actor_user_id=connector.user_id)
    db.commit()
    if outcome.status_flipped_to_auth_invalid:
        _notify_dj_auth_invalid(db, connector)
    return outcome


async def run_monitor_pass(db: Session) -> int:
    """Run one full pass of the monitor: check every due connector.

    Returns the number of connectors checked. Exposed for tests and for the
    background loop. Sequential — see module docstring.
    """
    due = _select_due_connectors(db)
    if not due:
        return 0

    checked = 0
    for connector in due:
        try:
            await _check_one(db, connector)
        except Exception:  # noqa: BLE001 — keep the loop alive
            logger.exception("health monitor: error checking connector %s", connector.id)
            # Defensive: rollback any half-applied state from the failed check
            # so the next connector starts on a clean session.
            with contextlib.suppress(Exception):
                db.rollback()
        checked += 1
        if _PER_CHECK_SLEEP_SECONDS > 0 and checked < len(due):
            await asyncio.sleep(_PER_CHECK_SLEEP_SECONDS)
    return checked


def _run_monitor_pass_sync() -> int:
    """Synchronous wrapper for ``run_monitor_pass`` used by the background loop.

    Each pass opens its own ``SessionLocal`` so the loop doesn't hold a
    long-lived connection between scans. ``asyncio.run`` is fine here
    because this function is executed in ``asyncio.to_thread`` from the
    main event loop, not on the loop thread itself.
    """
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return asyncio.run(run_monitor_pass(db))
    finally:
        db.close()


async def health_monitor_loop() -> None:
    """Background task — runs forever, scanning every ``HEALTH_MONITOR_SCAN_INTERVAL_SECONDS``.

    Wrapped in a try/except so a single bug doesn't kill the loop; logs the
    exception and sleeps before retrying.
    """
    # First sleep before first pass so startup isn't blocked by N upstream
    # round-trips on cold boot.
    await asyncio.sleep(HEALTH_MONITOR_SCAN_INTERVAL_SECONDS)
    while True:
        try:
            checked = await asyncio.to_thread(_run_monitor_pass_sync)
            if checked:
                logger.info("llm health monitor pass: checked %s connectors", checked)
        except Exception:  # noqa: BLE001 — loop must survive any error
            logger.exception("llm health monitor loop error")
        await asyncio.sleep(HEALTH_MONITOR_SCAN_INTERVAL_SECONDS)
