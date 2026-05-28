# Fix SSE Stream Pooled DB Connection Leak Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the public SSE `event_stream` endpoint from pinning a pooled DB connection for the entire (potentially unbounded) lifetime of an EventSource connection, which exhausts the pool (size 5 + overflow 10 = 15) under modest guest load.

**Architecture:** Remove the `db: Session = Depends(get_db)` request-scoped dependency from `event_stream`. Run the one-shot existence/auth check inside a short-lived `with SessionLocal() as s:` block that is fully closed (connection returned to the pool) BEFORE the `EventSourceResponse` is returned. The async generator currently performs no per-tick DB access, so it opens no session; if future per-tick DB access is needed it must open its own short-lived `SessionLocal()` session. Existence/auth error responses (404 unknown, 410 archived/expired) are preserved exactly.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (QueuePool), sse-starlette, pytest.

---

### Task 1: Regression test proving idle SSE streams hold ~0 pooled DB connections

**Files:**
- Test: `server/tests/test_sse_pool.py` (create)

The existing `client`/`db` fixtures override `get_db` with a single shared `StaticPool` SQLite session, so they cannot measure the production `QueuePool`. This test exercises the real `event_stream` endpoint function directly against a real `SessionLocal`-backed engine, asserting the function returns (existence check done) with the pool fully checked back in, and that the returned generator can be opened/closed without checking out a connection.

- [ ] **Step 1: Write the failing test**

```python
"""Regression test for issue #356 — SSE event_stream must NOT pin a pooled
DB connection for the lifetime of the stream.

Before the fix, event_stream declared `db: Session = Depends(get_db)`, so
FastAPI held the session (and its checked-out QueuePool connection) open
until the request finished — which for an EventSource never happens while
the browser holds it open. ~15 concurrent guest viewers exhausted the pool.

These tests bypass the conftest StaticPool override and drive a real
QueuePool engine so engine.pool.checkedout() is meaningful.
"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request as StarletteRequest

from app.core.time import utcnow
from app.models.base import Base
from app.models.user import User
from app.models.event import Event
from app.services.auth import get_password_hash


@pytest.fixture()
def pooled_engine(monkeypatch):
    """A real file-backed SQLite engine using QueuePool (default), so
    engine.pool.checkedout() reflects actual checked-out connections.

    Patches app.db.session.SessionLocal AND the name already imported into
    app.api.sse so the endpoint resolves our pooled session factory.
    """
    import app.db.session as db_session
    import app.api.sse as sse_module

    engine = create_engine(
        "sqlite:///file:sse_pool_test?mode=memory&cache=shared&uri=true",
        pool_size=5,
        max_overflow=10,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(db_session, "SessionLocal", TestSession)
    monkeypatch.setattr(sse_module, "SessionLocal", TestSession, raising=False)

    # Seed an active event using a short-lived session.
    with TestSession() as s:
        user = User(
            username="pooluser",
            password_hash=get_password_hash("poolpassword123"),
            role="dj",
        )
        s.add(user)
        s.commit()
        s.refresh(user)
        evt = Event(
            code="POOL01",
            join_code="POOLJN",
            name="Pool Event",
            created_by_user_id=user.id,
            expires_at=utcnow() + timedelta(hours=6),
        )
        s.add(evt)
        s.commit()

    try:
        yield engine, TestSession
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_request(code: str) -> StarletteRequest:
    """Minimal ASGI scope for a GET that reports as connected."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/api/public/events/{code}/stream",
        "headers": [],
        "query_string": b"",
    }

    async def receive():  # pragma: no cover - never drained in these tests
        return {"type": "http.disconnect"}

    return StarletteRequest(scope, receive)


def test_event_stream_returns_with_pool_checked_in(pooled_engine):
    """After event_stream() returns, the existence-check connection must be
    back in the pool (checkedout() == 0)."""
    from app.api.sse import event_stream

    engine, _ = pooled_engine
    assert engine.pool.checkedout() == 0

    req = _make_request("POOLJN")
    response = asyncio.run(event_stream(code="POOLJN", request=req))

    # EventSourceResponse created, generator not yet iterated.
    assert engine.pool.checkedout() == 0


def test_n_concurrent_idle_streams_hold_zero_pool_connections(pooled_engine):
    """N concurrent open (idle) SSE streams must hold ~0 pooled connections.

    Open N generators (past pool_size + max_overflow = 15), prime each one
    tick so the generator body is actively suspended on queue.get(), then
    assert the pool has 0 checked-out connections. Before the fix this would
    be N (one pinned per stream) and would TimeoutError past 15.
    """
    from app.api.sse import event_stream

    engine, _ = pooled_engine
    n = 25  # well past pool capacity (15)

    async def drive():
        generators = []
        for _ in range(n):
            req = _make_request("POOLJN")
            resp = await event_stream(code="POOLJN", request=req)
            gen = resp.body_iterator
            generators.append(gen)

        # Prime each generator one step so it subscribes and suspends on
        # queue.get(); give the event loop a tick to settle.
        primer_tasks = [asyncio.ensure_future(g.__anext__()) for g in generators]
        await asyncio.sleep(0.05)

        checked_out = engine.pool.checkedout()

        # Cancel the primers and close generators to release subscriptions.
        for t in primer_tasks:
            t.cancel()
        for g in generators:
            await g.aclose()

        return checked_out

    checked_out = asyncio.run(drive())
    assert checked_out == 0, (
        f"Expected 0 pooled connections held by {n} idle SSE streams, "
        f"got {checked_out} — the stream is pinning DB connections."
    )


def test_event_stream_preserves_404_for_unknown_event(pooled_engine):
    """Existence check must still reject unknown codes with 404."""
    from fastapi import HTTPException

    from app.api.sse import event_stream

    req = _make_request("NOEXIS")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(event_stream(code="NOEXIS", request=req))
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `server/`): `.venv/bin/pytest tests/test_sse_pool.py -v`
Expected: `test_event_stream_returns_with_pool_checked_in` raises `TypeError` because `event_stream` still requires the `db` parameter (FastAPI `Depends` default is not auto-injected when calling the function directly), and/or the pool assertions fail. RED.

- [ ] **Step 3: Implement the fix in `server/app/api/sse.py`**

Remove the `db: Session = Depends(get_db)` parameter. Import `SessionLocal`. Run the existence check in a short-lived session closed before returning.

```python
"""SSE streaming endpoint for real-time event updates (no authentication required)."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.core.rate_limit import limiter
from app.db.session import SessionLocal
from app.services.event import EventLookupResult, get_event_by_join_code_with_status
from app.services.event_bus import get_event_bus

logger = logging.getLogger(__name__)
router = APIRouter()

DISCONNECT_CHECK_INTERVAL = 15  # seconds


async def _event_generator(
    request: Request,
    event_code: str,
) -> Any:
    """Yield SSE events for a given event code until the client disconnects.

    Keepalive pings are handled by sse-starlette's built-in ping task (every 15s).
    This generator only yields actual events. The timeout on queue.get() lets us
    periodically check for client disconnect without blocking forever.

    NOTE (issue #356): this generator deliberately holds NO DB session. If a
    future change needs per-tick DB access it MUST open its own short-lived
    `with SessionLocal() as s:` session per tick and close it before awaiting —
    never hold a pooled connection across the stream lifetime.
    """
    bus = get_event_bus()
    queue = bus.subscribe(event_code)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                message = await asyncio.wait_for(queue.get(), timeout=DISCONNECT_CHECK_INTERVAL)
                yield {
                    "event": message["event"],
                    "data": json.dumps(message["data"]),
                }
            except TimeoutError:
                # No event received — loop to check is_disconnected()
                continue
    finally:
        bus.unsubscribe(event_code, queue)


@router.get("/events/{code}/stream")
@limiter.limit("10/minute")
async def event_stream(
    code: str,
    request: Request,
) -> EventSourceResponse:
    """Public SSE endpoint for real-time event updates.

    SECURITY (CRIT-5): rate-limited and existence-checked. Before this fix,
    the endpoint had no rate limit and no existence check, allowing
    unauthenticated DoS (unlimited long-lived connections exhausting FDs)
    and passive eavesdropping via 6-char event-code brute force.

    POOL SAFETY (issue #356): the existence/auth check runs in a short-lived
    session that is closed (its pooled connection returned) BEFORE the
    EventSourceResponse is returned. An EventSource connection can stay open
    indefinitely, so we must NOT hold a request-scoped get_db session across
    the stream lifetime — doing so pinned one pooled connection per open
    stream and exhausted the QueuePool (size 5 + overflow 10) under guest load.

    Event types:
    - request_created: New request submitted
    - request_status_changed: Request status update
    - now_playing_changed: Now-playing track update
    - requests_bulk_update: Batch accept/reject
    - bridge_status_changed: Bridge connect/disconnect
    """
    with SessionLocal() as db:
        event, result = get_event_by_join_code_with_status(db, code)
        if result == EventLookupResult.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Event not found")
        if result == EventLookupResult.ARCHIVED:
            raise HTTPException(status_code=410, detail="Event has been archived")
        if result == EventLookupResult.EXPIRED:
            raise HTTPException(status_code=410, detail="Event has expired")
        event_code = event.code

    return EventSourceResponse(
        _event_generator(request, event_code),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run (from `server/`): `.venv/bin/pytest tests/test_sse_pool.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Run existing SSE security tests to confirm no regression**

Run (from `server/`): `.venv/bin/pytest tests/test_sse_security.py -v`
Expected: all PASS (404/410 existence checks + rate limit preserved).

- [ ] **Step 6: Full backend CI gate**

Run (from `server/`):
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/bandit -r app -c pyproject.toml -q
.venv/bin/pytest --tb=short -q
```
Expected: all green, coverage >= 80%.

- [ ] **Step 7: Commit**

```bash
git add server/app/api/sse.py server/tests/test_sse_pool.py docs/superpowers/plans/2026-05-26-sse-stream-pooled-db-connection-leak.md
git commit -m "fix(sse): don't pin a pooled DB connection for the SSE stream lifetime (#356)"
```

---

## Self-Review

**Spec coverage:**
- "Open SSE streams no longer hold a pooled DB connection while idle" → fix removes `Depends(get_db)`, uses `with SessionLocal()` closed before returning; `test_n_concurrent_idle_streams_hold_zero_pool_connections` proves it.
- "A test confirms N concurrent open streams consume ~0 idle pool connections" → `test_n_concurrent_idle_streams_hold_zero_pool_connections` (N=25 > pool capacity 15).
- "Existence/auth checks preserved" → `test_event_stream_preserves_404_for_unknown_event` + existing `test_sse_security.py`.

**Placeholder scan:** none.

**Type consistency:** `event_stream(code, request)`, `_event_generator(request, event_code)`, `SessionLocal()` — consistent across plan and fix.
