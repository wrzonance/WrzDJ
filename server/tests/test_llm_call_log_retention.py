"""Tests for configurable llm_call_log retention (issue #342).

Covers:
- The purge helper deletes only rows older than the supplied window.
- The daily cleanup job reads the retention window from system settings each
  run (no hardcoded constant), so an admin change takes effect on the next pass.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.llm_connector import LlmCallLog, LlmConnector
from app.services.llm.connector_storage import purge_call_log_older_than
from app.services.system_settings import update_system_settings


def _make_connector(db: Session, user_id: int) -> LlmConnector:
    row = LlmConnector(
        user_id=user_id,
        connector_type="openai_apikey",
        display_name="Mine",
        status="active",
        credentials=json.dumps({"api_key": "sk-x"}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _seed_call_log(db: Session, connector_id: int, *, age_days: int) -> LlmCallLog:
    # Set created_at explicitly at construction so the backdated timestamp wins
    # over the column's server_default.
    row = LlmCallLog(
        connector_id=connector_id,
        purpose="recommendation",
        status="ok",
        latency_ms=100,
        tokens_in=10,
        tokens_out=5,
        created_at=utcnow() - timedelta(days=age_days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class TestPurgeHelper:
    def test_deletes_only_older_than_window(self, db: Session, test_user):
        connector = _make_connector(db, test_user.id)
        old = _seed_call_log(db, connector.id, age_days=40)
        recent = _seed_call_log(db, connector.id, age_days=5)
        # Capture ids before the bulk delete — accessing attributes on a deleted
        # ORM instance afterwards would trigger a reload error.
        old_id, recent_id = old.id, recent.id

        deleted = purge_call_log_older_than(db, retention_days=30)
        db.commit()

        assert deleted == 1
        ids = {r.id for r in db.query(LlmCallLog.id).all()}
        assert recent_id in ids
        assert old_id not in ids

    def test_no_rows_to_delete_returns_zero(self, db: Session, test_user):
        connector = _make_connector(db, test_user.id)
        _seed_call_log(db, connector.id, age_days=5)

        deleted = purge_call_log_older_than(db, retention_days=30)
        db.commit()

        assert deleted == 0
        assert db.query(LlmCallLog).count() == 1

    def test_rejects_out_of_bounds_window_without_deleting(self, db: Session, test_user):
        # A corrupt/tampered persisted value outside the 7-365 contract must fail
        # closed: raise before deleting, never push the cutoff to now/future and
        # wipe history. The daily cleanup loop catches this and retries next pass.
        connector = _make_connector(db, test_user.id)
        _seed_call_log(db, connector.id, age_days=5)

        for bad in (0, -1, 6, 366, 100000):
            with pytest.raises(ValueError):
                purge_call_log_older_than(db, retention_days=bad)
            db.rollback()

        assert db.query(LlmCallLog).count() == 1

    def test_boundary_row_at_exactly_window_kept(self, db: Session, test_user):
        # A row aged just under the window must be kept; just over must go.
        connector = _make_connector(db, test_user.id)
        just_under = _seed_call_log(db, connector.id, age_days=29)
        just_over = _seed_call_log(db, connector.id, age_days=31)
        under_id, over_id = just_under.id, just_over.id

        purge_call_log_older_than(db, retention_days=30)
        db.commit()

        ids = {r.id for r in db.query(LlmCallLog.id).all()}
        assert under_id in ids
        assert over_id not in ids


class TestCleanupReadsSettings:
    """The daily cleanup job must read the retention window from settings each
    run, not from a hardcoded constant."""

    def test_cleanup_honors_admin_changed_window(self, db: Session, test_user):
        connector = _make_connector(db, test_user.id)
        # A row aged 20 days survives the default 30-day window but should be
        # purged once the admin shortens retention to 7 days.
        _seed_call_log(db, connector.id, age_days=20)

        # Admin shortens retention.
        update_system_settings(db, llm_call_log_retention_days=7)

        import app.main as main_module

        main_module._run_llm_call_log_cleanup()

        assert db.query(LlmCallLog).count() == 0

    def test_cleanup_keeps_rows_within_window(self, db: Session, test_user):
        connector = _make_connector(db, test_user.id)
        _seed_call_log(db, connector.id, age_days=20)

        # Default window (30) keeps the 20-day-old row.
        import app.main as main_module

        main_module._run_llm_call_log_cleanup()

        assert db.query(LlmCallLog).count() == 1
