"""TDD guard for CRIT-5 — SSE stream must validate event existence
and rate-limit connection opens.

Before the fix, GET /api/public/events/{code}/stream had no auth,
no existence check, and no rate limit. An unauthenticated attacker
could open unlimited long-lived SSE connections (DoS) or brute-force
6-char event codes to passively eavesdrop on real-time events.

See docs/security/audit-2026-04-08.md CRIT-5.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.event import Event
from app.models.user import User


class TestSseExistenceCheck:
    """CRIT-5 guard: existence check must run before the async generator."""

    def test_sse_returns_404_for_unknown_event(self, client: TestClient):
        """An unknown event code must return 404 immediately,
        not silently subscribe to a ghost event bus channel."""
        resp = client.get(
            "/api/public/events/NONEXIST/stream",
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 404

    def test_sse_returns_404_for_archived_event(
        self,
        client: TestClient,
        db: Session,
        test_user: User,
    ):
        """Archived events must not be streamable."""
        evt = Event(
            code="ARCHIV",
            join_code="8MWM4Y",
            name="Archived",
            created_by_user_id=test_user.id,
            expires_at=utcnow() + timedelta(hours=6),
            archived_at=utcnow(),
        )
        db.add(evt)
        db.commit()

        resp = client.get(
            f"/api/public/events/{evt.join_code}/stream",
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code in (404, 410)

    def test_sse_returns_404_for_expired_event(
        self,
        client: TestClient,
        db: Session,
        test_user: User,
    ):
        """Expired events must not be streamable."""
        evt = Event(
            code="EXPIRD",
            join_code="UNZC4W",
            name="Expired",
            created_by_user_id=test_user.id,
            expires_at=utcnow() - timedelta(hours=1),
        )
        db.add(evt)
        db.commit()

        resp = client.get(
            f"/api/public/events/{evt.join_code}/stream",
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code in (404, 410)


class TestSseRateLimit:
    """CRIT-5 guard: rate-limit must fire on connection open."""

    @pytest.fixture(autouse=True)
    def _enable_rate_limit(self, monkeypatch):
        """Force-enable the rate limiter for this test class.

        Rate limiting is disabled by default in dev/tests via
        settings.is_rate_limit_enabled, so we monkeypatch the limiter
        instance's enabled attribute directly and reset its storage.
        """
        from app.core.rate_limit import limiter

        original_enabled = limiter.enabled
        limiter.enabled = True
        try:
            # Clear any residual rate-limit state from prior tests
            limiter.reset()
        except Exception:
            pass
        yield
        limiter.enabled = original_enabled
        try:
            limiter.reset()
        except Exception:
            pass

    def test_sse_rate_limited_per_ip(
        self,
        client: TestClient,
    ):
        """Rapidly opening >10 SSE connections per minute must return 429
        on at least one of the excess attempts.

        Uses a nonexistent event code: the rate-limit decorator fires
        BEFORE the route body, so the first 10 requests return 404 and
        subsequent requests return 429. This avoids opening real SSE
        streams (which would hang the TestClient)."""
        responses = []
        for _ in range(15):
            r = client.get(
                "/api/public/events/NOTEXIST/stream",
                headers={"Accept": "text/event-stream"},
            )
            responses.append(r.status_code)
        assert 429 in responses, (
            f"Expected at least one 429 among 15 rapid requests, got {responses}"
        )
        # Sanity: early requests should be 404 (existence check runs after limit)
        assert 404 in responses
