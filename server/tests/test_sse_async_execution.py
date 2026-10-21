"""The one-shot SSE event lookup must not block the server event loop."""

import asyncio
import threading
from types import SimpleNamespace

import httpx

from app.services.event import EventLookupResult


def test_sse_event_lookup_runs_off_the_async_event_loop(monkeypatch):
    from app.api import sse
    from app.main import create_app, no_background_lifespan

    lookup_waiting = threading.Event()
    release_lookup = threading.Event()

    def blocking_session_local():
        class BlockingSession:
            def __enter__(self):
                lookup_waiting.set()
                release_lookup.wait(timeout=1)
                lookup_waiting.clear()
                return self

            def __exit__(self, *_args):
                return False

        return BlockingSession()

    async def one_event(_request, _event_code):
        yield {"event": "request_created", "data": {"id": 42}}

    monkeypatch.setattr(sse, "SessionLocal", blocking_session_local)
    monkeypatch.setattr(
        sse,
        "get_event_by_public_code_with_status",
        lambda _db, _code: (SimpleNamespace(code="EVENT1"), EventLookupResult.FOUND),
    )
    monkeypatch.setattr(sse, "_event_generator", one_event)

    async def exercise_request():
        app = create_app(lifespan_context=no_background_lifespan)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            loop_progressed_during_lookup = asyncio.Event()
            response_task = asyncio.create_task(
                client.get(
                    "/api/public/events/EVNT01/stream",
                    headers={"Accept": "text/event-stream"},
                )
            )

            async def observe_loop():
                while not response_task.done():
                    if lookup_waiting.is_set():
                        loop_progressed_during_lookup.set()
                        release_lookup.set()
                        return
                    await asyncio.sleep(0)

            observer = asyncio.create_task(observe_loop())
            response = await response_task
            await observer

        assert response.status_code == 200
        assert "data: {'id': 42}" in response.text
        assert loop_progressed_during_lookup.is_set(), (
            "the ASGI event loop could not run while the synchronous DB lookup was blocked"
        )

    asyncio.run(exercise_request())
