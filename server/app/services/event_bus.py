"""In-memory pub/sub event bus for SSE real-time updates.

One bus per process. Channels are keyed by event_code.
Subscribers are asyncio.Queue instances.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


class _SubscriberQueue(asyncio.Queue[dict[str, Any]]):
    """Queue that registers the loop of its first asynchronous consumer."""

    def __init__(
        self,
        event_code: str,
        bind_loop: Callable[
            [str, asyncio.Queue[dict[str, Any]], asyncio.AbstractEventLoop],
            None,
        ],
    ) -> None:
        super().__init__(maxsize=64)
        self._event_code = event_code
        self._bind_loop = bind_loop

    async def get(self) -> dict[str, Any]:
        self._bind_loop(self._event_code, self, asyncio.get_running_loop())
        return await super().get()


class EventBus:
    """Process-local pub/sub for broadcasting events to SSE subscribers."""

    def __init__(self) -> None:
        self._channels: dict[
            str,
            dict[asyncio.Queue[dict[str, Any]], asyncio.AbstractEventLoop | None],
        ] = defaultdict(dict)
        self._lock = Lock()

    def subscribe(self, event_code: str) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to events for a given event code. Returns a Queue to read from."""
        queue: asyncio.Queue[dict[str, Any]] = _SubscriberQueue(
            event_code,
            self._bind_subscriber_loop,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Keep synchronous queue usage available for callers that only publish directly.
            loop = None
        with self._lock:
            subscribers = self._channels[event_code]
            subscribers[queue] = loop
            count = len(subscribers)
        logger.debug("SSE subscriber added for %s (total: %d)", event_code, count)
        return queue

    def _bind_subscriber_loop(
        self,
        event_code: str,
        queue: asyncio.Queue[dict[str, Any]],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        with self._lock:
            subscribers = self._channels.get(event_code)
            if subscribers is None or queue not in subscribers:
                return
            current_loop = subscribers[queue]
            if current_loop is None:
                subscribers[queue] = loop
            elif current_loop is not loop:
                raise RuntimeError("Event bus subscriber is already bound to another event loop")

    def unsubscribe(self, event_code: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber."""
        with self._lock:
            subscribers = self._channels.get(event_code)
            if subscribers is None:
                return
            subscribers.pop(queue, None)
            if not subscribers:
                del self._channels[event_code]

    def publish(self, event_code: str, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Publish an event to all subscribers of an event code.

        Non-blocking: drops messages for full queues (slow consumers).
        Safe to call from sync code via the module-level helper. Cross-thread
        delivery is scheduled on each subscriber's owning event loop.
        """
        message = {"event": event_type, "data": data or {}}
        with self._lock:
            subscribers = list(self._channels.get(event_code, {}).items())

        try:
            publishing_loop = asyncio.get_running_loop()
        except RuntimeError:
            publishing_loop = None

        for queue, subscriber_loop in subscribers:
            if subscriber_loop is None or subscriber_loop is publishing_loop:
                self._deliver(event_code, queue, subscriber_loop, message)
                continue
            if subscriber_loop.is_closed():
                self._remove_closed_subscriber(event_code, queue, subscriber_loop)
                continue
            try:
                subscriber_loop.call_soon_threadsafe(
                    self._deliver,
                    event_code,
                    queue,
                    subscriber_loop,
                    message,
                )
            except RuntimeError:
                # The loop may close between is_closed() and call_soon_threadsafe().
                self._remove_closed_subscriber(event_code, queue, subscriber_loop)

    def _deliver(
        self,
        event_code: str,
        queue: asyncio.Queue[dict[str, Any]],
        subscriber_loop: asyncio.AbstractEventLoop | None,
        message: dict[str, Any],
    ) -> None:
        rebound_loop = None
        with self._lock:
            subscribers = self._channels.get(event_code)
            if subscribers is None or queue not in subscribers:
                return
            current_loop = subscribers[queue]
            if current_loop is not subscriber_loop:
                if subscriber_loop is None and current_loop is not None:
                    rebound_loop = current_loop
                else:
                    return
            else:
                self._enqueue(event_code, queue, message)
                return

        if rebound_loop.is_closed():
            self._remove_closed_subscriber(event_code, queue, rebound_loop)
            return
        try:
            rebound_loop.call_soon_threadsafe(
                self._deliver,
                event_code,
                queue,
                rebound_loop,
                message,
            )
        except RuntimeError:
            # The loop may close between is_closed() and call_soon_threadsafe().
            self._remove_closed_subscriber(event_code, queue, rebound_loop)

    @staticmethod
    def _enqueue(
        event_code: str,
        queue: asyncio.Queue[dict[str, Any]],
        message: dict[str, Any],
    ) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(
                "SSE queue full for %s, dropping %s event",
                event_code,
                message["event"],
            )

    def _remove_closed_subscriber(
        self,
        event_code: str,
        queue: asyncio.Queue[dict[str, Any]],
        subscriber_loop: asyncio.AbstractEventLoop,
    ) -> None:
        with self._lock:
            subscribers = self._channels.get(event_code)
            if subscribers is None or subscribers.get(queue) is not subscriber_loop:
                return
            del subscribers[queue]
            if not subscribers:
                del self._channels[event_code]

    def subscriber_count(self, event_code: str) -> int:
        """Return the number of active subscribers for an event code."""
        with self._lock:
            return len(self._channels.get(event_code, {}))


# Singleton instance
_bus = EventBus()


def get_event_bus() -> EventBus:
    """Get the singleton event bus instance."""
    return _bus


def publish_event(event_code: str, event_type: str, data: dict[str, Any] | None = None) -> None:
    """Convenience function to publish an event on the singleton bus."""
    _bus.publish(event_code, event_type, data)
