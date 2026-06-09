"""Tests for the background connector health monitor (issue #340).

Covers:
- Only active connectors that are overdue get checked.
- Disabled / fresh connectors are skipped.
- A successful pass writes ``last_health_check_at`` on each due connector.
- A flip from active → auth_invalid triggers a notification.
- A pass survives an adapter exception on one connector and keeps going.
- Per-connector jitter is deterministic so the schedule doesn't shuffle.
- The env-var interval is clamped to safe bounds.
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.time import utcnow
from app.models.llm_connector import (
    HEALTH_CHECK_AUTH_INVALID,
    HEALTH_CHECK_OK,
    STATUS_ACTIVE,
    STATUS_AUTH_INVALID,
    STATUS_DISABLED,
    LlmConnector,
)
from app.services.llm.exceptions import AuthInvalid
from app.services.llm.health_monitor import (
    _get_interval_seconds,
    _is_due,
    _jitter_factor,
    _select_due_connectors,
    run_monitor_pass,
)

_counter = {"n": 0}


def _make(db, user_id: int, *, status: str = STATUS_ACTIVE, last_check: object = None):
    _counter["n"] += 1
    row = LlmConnector(
        user_id=user_id,
        connector_type="openai_apikey",
        display_name=f"user{user_id}-conn-{_counter['n']}",
        status=status,
        credentials=json.dumps({"api_key": "sk-key12345678901234567890"}),
        last_health_check_at=last_check,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------- env-var interval ----------


class TestIntervalConfig:
    def test_default_interval_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("LLM_HEALTH_CHECK_INTERVAL_HOURS", raising=False)
        assert _get_interval_seconds() == 6 * 3600

    def test_env_override_applied(self, monkeypatch):
        monkeypatch.setenv("LLM_HEALTH_CHECK_INTERVAL_HOURS", "12")
        assert _get_interval_seconds() == 12 * 3600

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("LLM_HEALTH_CHECK_INTERVAL_HOURS", "not-a-number")
        assert _get_interval_seconds() == 6 * 3600

    def test_too_low_clamped_to_floor(self, monkeypatch):
        monkeypatch.setenv("LLM_HEALTH_CHECK_INTERVAL_HOURS", "0")
        assert _get_interval_seconds() == 3600  # 1h floor

    def test_too_high_clamped_to_ceiling(self, monkeypatch):
        monkeypatch.setenv("LLM_HEALTH_CHECK_INTERVAL_HOURS", "9999")
        assert _get_interval_seconds() == 168 * 3600  # 7d ceiling


# ---------- jitter ----------


class TestJitter:
    def test_jitter_is_deterministic_per_id(self):
        assert _jitter_factor(1) == _jitter_factor(1)
        assert _jitter_factor(42) == _jitter_factor(42)

    def test_jitter_within_bounds(self):
        # All factors in [0.7, 1.3) per the docstring contract.
        for i in range(1, 100):
            f = _jitter_factor(i)
            assert 0.7 <= f < 1.3

    def test_jitter_spreads_connectors(self):
        # Sample a few hundred ids — the band should be reasonably populated
        # (not all clumped at one end).
        factors = [_jitter_factor(i) for i in range(1, 300)]
        low = sum(1 for f in factors if f < 1.0)
        high = sum(1 for f in factors if f >= 1.0)
        # Not a statistics test — just confirms the hash isn't a constant.
        assert low > 50
        assert high > 50


# ---------- _is_due / _select_due_connectors ----------


class TestDueSelection:
    def test_never_checked_is_due(self, db, test_user):
        row = _make(db, test_user.id, last_check=None)
        assert _is_due(row) is True

    def test_recently_checked_is_not_due(self, db, test_user):
        row = _make(db, test_user.id, last_check=utcnow() - timedelta(minutes=5))
        assert _is_due(row) is False

    def test_overdue_is_due(self, db, test_user, monkeypatch):
        # Force a tight interval so overdue triggers reliably regardless of jitter.
        monkeypatch.setenv("LLM_HEALTH_CHECK_INTERVAL_HOURS", "1")
        row = _make(db, test_user.id, last_check=utcnow() - timedelta(hours=24))
        assert _is_due(row) is True

    def test_select_due_skips_disabled(self, db, test_user):
        active = _make(db, test_user.id, status=STATUS_ACTIVE, last_check=None)
        _make(db, test_user.id, status=STATUS_DISABLED, last_check=None)
        _make(db, test_user.id, status=STATUS_AUTH_INVALID, last_check=None)

        due = _select_due_connectors(db)
        due_ids = [c.id for c in due]
        assert active.id in due_ids
        # auth_invalid + disabled are excluded — the monitor only re-checks
        # active connectors. (auth_invalid stays invalid until the DJ rotates.)
        assert len(due) == 1


# ---------- run_monitor_pass ----------


@pytest.mark.asyncio
async def test_monitor_pass_checks_every_due_connector(db, test_user):
    a = _make(db, test_user.id, last_check=None)
    b = _make(db, test_user.id, last_check=None)
    c = _make(db, test_user.id, status=STATUS_DISABLED, last_check=None)

    with (
        patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm.health_monitor._PER_CHECK_SLEEP_SECONDS",
            0,
        ),
    ):
        checked = await run_monitor_pass(db)

    assert checked == 2
    db.refresh(a)
    db.refresh(b)
    db.refresh(c)
    assert a.last_health_check_status == HEALTH_CHECK_OK
    assert b.last_health_check_status == HEALTH_CHECK_OK
    assert c.last_health_check_at is None  # disabled — skipped


@pytest.mark.asyncio
async def test_monitor_pass_notifies_on_first_flip_to_auth_invalid(db, test_user):
    row = _make(db, test_user.id, last_check=None)

    with (
        patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(side_effect=AuthInvalid("revoked upstream")),
        ),
        patch(
            "app.services.llm.health_monitor._PER_CHECK_SLEEP_SECONDS",
            0,
        ),
        patch(
            "app.services.llm.health_monitor._notify_dj_auth_invalid",
        ) as notify,
    ):
        await run_monitor_pass(db)

    db.refresh(row)
    assert row.status == STATUS_AUTH_INVALID
    assert row.last_health_check_status == HEALTH_CHECK_AUTH_INVALID
    notify.assert_called_once()
    notified_connector = notify.call_args.args[1]
    assert notified_connector.id == row.id


@pytest.mark.asyncio
async def test_monitor_pass_survives_individual_failure(db, test_user):
    good = _make(db, test_user.id, last_check=None)
    bad = _make(db, test_user.id, last_check=None)

    call_count = {"n": 0}

    async def fake_check(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("first one explodes")
        return None

    with (
        patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=fake_check,
        ),
        patch(
            "app.services.llm.health_monitor._PER_CHECK_SLEEP_SECONDS",
            0,
        ),
    ):
        checked = await run_monitor_pass(db)

    # Both checks were attempted (even after the first one's adapter raised).
    assert checked == 2
    # At least one of the two was successfully updated.
    db.refresh(good)
    db.refresh(bad)
    statuses = [good.last_health_check_status, bad.last_health_check_status]
    assert HEALTH_CHECK_OK in statuses


@pytest.mark.asyncio
async def test_monitor_pass_no_due_connectors_returns_zero(db, test_user):
    # Just-checked connector — not due.
    _make(db, test_user.id, last_check=utcnow() - timedelta(minutes=1))

    with patch(
        "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
        new=AsyncMock(return_value=None),
    ):
        checked = await run_monitor_pass(db)
    assert checked == 0


# ---------- notification ----------


def test_notify_dj_falls_back_to_log_when_email_not_configured(db, test_user, caplog):
    from app.services.email_sender import EmailNotConfiguredError
    from app.services.llm.health_monitor import _notify_dj_auth_invalid

    # User HAS an email — the failure is at the sender layer (no Resend key).
    test_user.email = "dj@example.com"
    db.commit()
    row = _make(db, test_user.id)

    with patch(
        "app.services.email_sender.send_connector_auth_invalid_notification",
        side_effect=EmailNotConfiguredError("nope"),
    ):
        with caplog.at_level("WARNING"):
            _notify_dj_auth_invalid(db, row)

    assert any("email not configured" in r.message.lower() for r in caplog.records)


def test_notify_dj_logs_when_user_has_no_email(db, caplog):
    from app.models.user import User
    from app.services.llm.health_monitor import _notify_dj_auth_invalid

    user_noemail = User(
        username="silent",
        password_hash="x",
        email=None,
        role="dj",
    )
    db.add(user_noemail)
    db.commit()
    db.refresh(user_noemail)
    row = _make(db, user_noemail.id)

    with caplog.at_level("WARNING"):
        _notify_dj_auth_invalid(db, row)
    assert any("no email on file" in r.message.lower() for r in caplog.records)


def test_notify_dj_sends_email_when_configured(db, test_user):
    from app.services.llm.health_monitor import _notify_dj_auth_invalid

    test_user.email = "dj@example.com"
    db.commit()
    row = _make(db, test_user.id)

    with patch(
        "app.services.email_sender.send_connector_auth_invalid_notification",
    ) as sender:
        _notify_dj_auth_invalid(db, row)

    sender.assert_called_once()
    kwargs = sender.call_args.kwargs
    assert kwargs["to_address"] == "dj@example.com"
    assert kwargs["display_name"] == row.display_name
    assert kwargs["connector_type"] == row.connector_type
