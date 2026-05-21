"""Assert no IP-derived logging functions or log records exist.

These tests guard against IP-derived data leaking into application logs.
They FAIL on the pre-cleanup codebase (the helpers exist, the logger emits)
and PASS after the cleanup is complete.

See: docs/RECOVERY-IP-IDENTITY.md
"""

import logging
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.activity_log import ActivityLog
from app.models.event import Event
from app.models.guest import Guest


def _enable_collection(db: Session, event: Event) -> None:
    now = utcnow()
    event.collection_opens_at = now - timedelta(hours=1)
    event.live_starts_at = now + timedelta(hours=1)
    db.commit()
    db.refresh(event)


def test_get_client_fingerprint_function_removed():
    """The IP-fetching helper must not exist."""
    with pytest.raises(ImportError):
        from app.core.rate_limit import get_client_fingerprint  # noqa: F401


def test_mask_fingerprint_function_removed():
    """The hashed-IP tagging helper must not exist."""
    with pytest.raises(ImportError):
        from app.core.rate_limit import mask_fingerprint  # noqa: F401


def test_app_fingerprint_logger_does_not_emit(
    caplog: pytest.LogCaptureFixture,
    client: TestClient,
    db: Session,
    test_event: Event,
):
    """No log record may originate from the 'app.fingerprint' logger."""
    _enable_collection(db, test_event)
    caplog.set_level(logging.DEBUG)

    client.get(f"/api/public/collect/{test_event.code}/profile")
    client.post(
        f"/api/public/collect/{test_event.code}/profile",
        json={"nickname": "Tester"},
    )
    client.get(f"/api/public/events/{test_event.join_code}/has-requested")

    fp_records = [r for r in caplog.records if r.name == "app.fingerprint"]
    assert fp_records == [], (
        f"Logger 'app.fingerprint' emitted: {[r.getMessage() for r in fp_records]} "
        "— see docs/RECOVERY-IP-IDENTITY.md"
    )


def test_no_fp_resolve_substring_in_logs(
    caplog: pytest.LogCaptureFixture,
    client: TestClient,
    db: Session,
    test_event: Event,
):
    """No log line may contain the 'fp_resolve' marker (old structured-fp tag)."""
    _enable_collection(db, test_event)
    caplog.set_level(logging.DEBUG)

    client.get(f"/api/public/collect/{test_event.code}/profile")
    client.get(f"/api/public/collect/{test_event.code}/profile/me")
    client.post(
        f"/api/public/collect/{test_event.code}/profile",
        json={"nickname": "Tester"},
    )

    bad = [r.getMessage() for r in caplog.records if "fp_resolve" in r.getMessage()]
    assert bad == [], f"Found 'fp_resolve' in logs: {bad} — see docs/RECOVERY-IP-IDENTITY.md"


def test_collect_activity_log_messages_have_no_hashed_ip_tag(
    client: TestClient,
    db: Session,
    test_event: Event,
    test_guest: Guest,
):
    """log_activity rows must not contain 'Guest [<12 hex chars>]' style IP tags."""
    _enable_collection(db, test_event)

    client.cookies.clear()
    client.cookies.set("wrzdj_guest", test_guest.token)
    client.post(
        f"/api/public/collect/{test_event.code}/profile",
        json={"nickname": "LoggedIn"},
    )

    rows = db.query(ActivityLog).filter(ActivityLog.event_code == test_event.code).all()
    pattern = re.compile(r"Guest \[[0-9a-f]{12}\]")
    offenders = [row.message for row in rows if pattern.search(row.message)]
    assert offenders == [], (
        f"activity_log rows contain hashed-IP tags: {offenders} — see docs/RECOVERY-IP-IDENTITY.md"
    )
