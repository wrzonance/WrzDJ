"""Regression test for issue #356 — SSE event_stream must NOT pin a pooled
DB connection for the lifetime of the stream.

Before the fix, event_stream declared `db: Session = Depends(get_db)`, so
FastAPI held the session (and its checked-out QueuePool connection) open
until the request finished — which for an EventSource never happens while
the browser holds it open. ~15 concurrent guest viewers exhausted the pool
(pool_size=5 + max_overflow=10).

These tests bypass the conftest StaticPool override and drive a real
QueuePool engine so engine.pool.checkedout() is meaningful.
"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from starlette.requests import Request as StarletteRequest

from app.core.time import utcnow
from app.models.base import Base
from app.models.event import Event
from app.models.user import User
from app.services.auth import get_password_hash


@pytest.fixture()
def pooled_engine(monkeypatch):
    """A real shared-cache SQLite engine using QueuePool (default), so
    engine.pool.checkedout() reflects actual checked-out connections.

    Patches app.db.session.SessionLocal AND the name already imported into
    app.api.sse so the endpoint resolves our pooled session factory.
    """
    import app.api.sse as sse_module
    import app.db.session as db_session

    engine = create_engine(
        "sqlite:///file:sse_pool_test?mode=memory&cache=shared&uri=true",
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(db_session, "SessionLocal", test_session)
    monkeypatch.setattr(sse_module, "SessionLocal", test_session, raising=False)

    # Seed an active event using a short-lived session.
    with test_session() as s:
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
        yield engine, test_session
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_request(code: str) -> StarletteRequest:
    """Minimal ASGI scope for a GET that reports as a live, idle client.

    The nested ``receive`` callable must NOT return ``http.disconnect``: doing
    so makes ``StarletteRequest.is_disconnected()`` true on the first generator
    iteration and the SSE generator exits before it can ever await
    ``queue.get()``. That would mean the concurrency test (below) is asserting
    that *instantly-disconnected* streams hold zero pool connections — trivially
    true and useless as a regression for issue #356.

    Instead, ``receive`` suspends forever on a never-set ``asyncio.Event``,
    which matches a real live, idle SSE client that has opened the connection
    and is simply waiting for server-sent events. The handler then suspends on
    ``queue.get()`` as intended, and we can meaningfully assert
    ``pool.checkedout() == 0`` across N concurrent idle streams.
    """
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/api/public/events/{code}/stream",
        "headers": [],
        "query_string": b"",
    }

    never_disconnect = asyncio.Event()

    async def receive():  # pragma: no cover - suspended forever in these tests
        await never_disconnect.wait()
        # Unreachable: the event is never set. Return value satisfies type
        # checkers; runtime suspends indefinitely above.
        return {"type": "http.disconnect"}

    return StarletteRequest(scope, receive)


def test_event_stream_returns_with_pool_checked_in(pooled_engine):
    """After event_stream() returns, the existence-check connection must be
    back in the pool (checkedout() == 0)."""
    from app.api.sse import event_stream

    engine, _ = pooled_engine
    assert engine.pool.checkedout() == 0

    req = _make_request("POOLJN")
    asyncio.run(event_stream(code="POOLJN", request=req))

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
            generators.append(resp.body_iterator)

        # Prime each generator one step so it subscribes and suspends on
        # queue.get(); give the event loop a tick to settle.
        primer_tasks = [asyncio.ensure_future(g.__anext__()) for g in generators]
        await asyncio.sleep(0.05)

        # Sanity-check that streams are actually suspended (not instantly
        # exited). If receive() returns http.disconnect immediately, every
        # primer would already be done here and the pool-connection assertion
        # below would pass for the wrong reason.
        assert any(not t.done() for t in primer_tasks), (
            "streams did not remain open/idle — receive() must suspend, not "
            "return http.disconnect immediately"
        )

        checked_out = engine.pool.checkedout()

        # Cancel the primers, await their cancellation so the generators are
        # no longer running, then close them to release subscriptions.
        for t in primer_tasks:
            t.cancel()
        for t in primer_tasks:
            try:
                await t
            except (asyncio.CancelledError, BaseException):  # noqa: BLE001
                pass
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
