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
    ``with SessionLocal() as s:`` session per tick and close it before awaiting
    again — never hold a pooled connection across the stream lifetime.
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

    POOL SAFETY (issue #356): the one-shot existence/auth check runs inside a
    short-lived ``with SessionLocal()`` block whose pooled connection is
    returned BEFORE the EventSourceResponse is returned. An EventSource
    connection can stay open indefinitely, so we must NOT hold a
    request-scoped ``get_db`` session across the stream lifetime — doing so
    pinned one pooled connection per open stream and exhausted the QueuePool
    (size 5 + overflow 10 = 15 connections) under modest guest load.

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
