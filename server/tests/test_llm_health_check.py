"""Tests for the shared connector health-check helper (issues #340 + #346).

Covers:
- ``last_health_check_at`` / ``last_health_check_status`` are written on every
  invocation (success and failure).
- AuthInvalid flips ``status`` to ``auth_invalid`` and writes the
  ``connector_health_check_failed`` audit row only on the active→invalid
  transition (not when already invalid).
- Transient failures (rate_limited, provider_unavailable, quota_exceeded) do
  NOT flip the connector status — they only record the outcome.
- The manual /test endpoint produces the same observability columns and
  audit rows as the background monitor (no behavior drift between the two).
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

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
    LlmAuditEvent,
    LlmConnector,
)
from app.services.llm.exceptions import (
    AuthInvalid,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
)


def _make_connector(db, user_id: int, *, status: str = STATUS_ACTIVE) -> LlmConnector:
    row = LlmConnector(
        user_id=user_id,
        connector_type="openai_apikey",
        display_name="Tested",
        status=status,
        credentials=json.dumps({"api_key": "sk-key12345678901234567890"}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _audit_types(db, connector_id: int) -> list[str]:
    rows = (
        db.query(LlmAuditEvent)
        .filter(LlmAuditEvent.target_connector_id == connector_id)
        .order_by(LlmAuditEvent.id.asc())
        .all()
    )
    return [r.event_type for r in rows]


# ---------- helper API (shared between manual + background) ----------


class TestRunHealthCheckHelper:
    @pytest.mark.asyncio
    async def test_success_writes_columns_and_audit(self, db, test_user):
        from app.services.llm.health_check import run_health_check

        row = _make_connector(db, test_user.id)
        before = utcnow() - timedelta(seconds=1)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(return_value=None),
        ):
            outcome = await run_health_check(db, row, actor_user_id=test_user.id)
        db.commit()

        assert outcome.ok is True
        assert outcome.status == HEALTH_CHECK_OK
        assert outcome.status_flipped_to_auth_invalid is False

        db.refresh(row)
        assert row.last_health_check_status == HEALTH_CHECK_OK
        assert row.last_health_check_at is not None
        assert row.last_health_check_at >= before
        assert row.status == STATUS_ACTIVE
        assert row.last_error is None

        assert _audit_types(db, row.id) == [AUDIT_HEALTH_CHECK]

    @pytest.mark.asyncio
    async def test_auth_invalid_flips_status_and_emits_flipped_audit(self, db, test_user):
        from app.services.llm.health_check import run_health_check

        row = _make_connector(db, test_user.id, status=STATUS_ACTIVE)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(side_effect=AuthInvalid("nope")),
        ):
            outcome = await run_health_check(db, row, actor_user_id=test_user.id)
        db.commit()

        assert outcome.ok is False
        assert outcome.status == HEALTH_CHECK_AUTH_INVALID
        assert outcome.status_flipped_to_auth_invalid is True

        db.refresh(row)
        assert row.status == STATUS_AUTH_INVALID
        assert row.last_health_check_status == HEALTH_CHECK_AUTH_INVALID
        assert row.last_error == "auth_invalid"

        types = _audit_types(db, row.id)
        assert AUDIT_HEALTH_CHECK in types
        assert AUDIT_AUTH_INVALID_OBSERVED in types
        assert AUDIT_HEALTH_CHECK_FAILED in types

    @pytest.mark.asyncio
    async def test_auth_invalid_does_not_re_emit_flipped_when_already_invalid(self, db, test_user):
        from app.services.llm.health_check import run_health_check

        row = _make_connector(db, test_user.id, status=STATUS_AUTH_INVALID)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(side_effect=AuthInvalid("still broken")),
        ):
            outcome = await run_health_check(db, row, actor_user_id=test_user.id)
        db.commit()

        assert outcome.status_flipped_to_auth_invalid is False
        db.refresh(row)
        assert row.status == STATUS_AUTH_INVALID
        # health_check_failed should NOT be present — already broken on prior pass.
        types = _audit_types(db, row.id)
        assert AUDIT_HEALTH_CHECK_FAILED not in types

    @pytest.mark.asyncio
    async def test_auth_invalid_leaves_disabled_connector_disabled(self, db, test_user):
        from app.services.llm.health_check import run_health_check

        row = _make_connector(db, test_user.id, status=STATUS_DISABLED)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(side_effect=AuthInvalid("nope")),
        ):
            await run_health_check(db, row, actor_user_id=test_user.id)
        db.commit()

        db.refresh(row)
        # Disabled must stay disabled — admin force-revoke takes precedence.
        assert row.status == STATUS_DISABLED

    @pytest.mark.parametrize(
        ("exc", "expected_status"),
        [
            (RateLimited("slow down"), HEALTH_CHECK_RATE_LIMITED),
            (QuotaExceeded("quota"), HEALTH_CHECK_QUOTA_EXCEEDED),
            (ProviderUnavailable("5xx"), HEALTH_CHECK_PROVIDER_UNAVAILABLE),
        ],
    )
    @pytest.mark.asyncio
    async def test_transient_failures_record_outcome_but_do_not_flip_status(
        self, db, test_user, exc, expected_status
    ):
        from app.services.llm.health_check import run_health_check

        row = _make_connector(db, test_user.id, status=STATUS_ACTIVE)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(side_effect=exc),
        ):
            outcome = await run_health_check(db, row, actor_user_id=test_user.id)
        db.commit()

        assert outcome.ok is False
        assert outcome.status == expected_status

        db.refresh(row)
        # Transient — status stays active so the gateway will still try it.
        assert row.status == STATUS_ACTIVE
        assert row.last_health_check_status == expected_status

    @pytest.mark.asyncio
    async def test_unexpected_exception_records_error_and_does_not_raise(self, db, test_user):
        from app.services.llm.health_check import run_health_check

        row = _make_connector(db, test_user.id, status=STATUS_ACTIVE)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(side_effect=RuntimeError("totally unexpected")),
        ):
            outcome = await run_health_check(db, row, actor_user_id=test_user.id)
        db.commit()

        assert outcome.ok is False
        assert outcome.status == HEALTH_CHECK_ERROR
        db.refresh(row)
        # Status not flipped on truly unknown errors — DJ retries.
        assert row.status == STATUS_ACTIVE
        assert row.last_health_check_status == HEALTH_CHECK_ERROR

    @pytest.mark.asyncio
    async def test_success_after_auth_invalid_clears_status(self, db, test_user):
        from app.services.llm.health_check import run_health_check

        row = _make_connector(db, test_user.id, status=STATUS_AUTH_INVALID)
        row.last_error = "auth_invalid"
        db.commit()

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(return_value=None),
        ):
            outcome = await run_health_check(db, row, actor_user_id=test_user.id)
        db.commit()

        assert outcome.ok is True
        db.refresh(row)
        assert row.status == STATUS_ACTIVE
        assert row.last_error is None
        assert row.last_health_check_status == HEALTH_CHECK_OK


# ---------- manual /test endpoint parity ----------


class TestManualTestEndpointParity:
    """The DJ-triggered test button must produce the same observability + audit
    rows as the background monitor — that's the whole point of issue #346.
    """

    def test_test_endpoint_writes_health_columns_on_success(
        self, client: TestClient, auth_headers, db, test_user
    ):
        row = _make_connector(db, test_user.id)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(return_value=None),
        ):
            resp = client.post(f"/api/llm/connectors/{row.id}/test", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        db.refresh(row)
        assert row.last_health_check_status == HEALTH_CHECK_OK
        assert row.last_health_check_at is not None
        assert AUDIT_HEALTH_CHECK in _audit_types(db, row.id)

    def test_test_endpoint_writes_health_columns_on_auth_invalid(
        self, client: TestClient, auth_headers, db, test_user
    ):
        row = _make_connector(db, test_user.id)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(side_effect=AuthInvalid("nope")),
        ):
            resp = client.post(f"/api/llm/connectors/{row.id}/test", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["error_code"] == "auth_invalid"

        db.refresh(row)
        assert row.status == STATUS_AUTH_INVALID
        assert row.last_health_check_status == HEALTH_CHECK_AUTH_INVALID

    def test_test_endpoint_response_exposes_new_columns_via_listing(
        self, client: TestClient, auth_headers, db, test_user
    ):
        row = _make_connector(db, test_user.id)

        with patch(
            "app.services.llm.adapters.openai_apikey.OpenAIApiKeyAdapter.health_check",
            new=AsyncMock(return_value=None),
        ):
            client.post(f"/api/llm/connectors/{row.id}/test", headers=auth_headers)

        # The DJ listing now exposes the two new columns
        resp = client.get("/api/llm/connectors", headers=auth_headers)
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        e = entries[0]
        assert e["last_health_check_status"] == HEALTH_CHECK_OK
        assert e["last_health_check_at"] is not None
