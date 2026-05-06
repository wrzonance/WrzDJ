"""Tests for the in-memory event bus (SSE pub/sub)."""

import asyncio

from app.services.event_bus import EventBus, get_event_bus, publish_event


class TestEventBus:
    """Unit tests for EventBus class."""

    def test_subscribe_returns_queue(self):
        bus = EventBus()
        queue = bus.subscribe("EVT001")
        assert isinstance(queue, asyncio.Queue)

    def test_subscribe_increments_count(self):
        bus = EventBus()
        assert bus.subscriber_count("EVT001") == 0
        bus.subscribe("EVT001")
        assert bus.subscriber_count("EVT001") == 1
        bus.subscribe("EVT001")
        assert bus.subscriber_count("EVT001") == 2

    def test_unsubscribe_removes_subscriber(self):
        bus = EventBus()
        q = bus.subscribe("EVT001")
        assert bus.subscriber_count("EVT001") == 1
        bus.unsubscribe("EVT001", q)
        assert bus.subscriber_count("EVT001") == 0

    def test_unsubscribe_cleans_up_empty_channel(self):
        bus = EventBus()
        q = bus.subscribe("EVT001")
        bus.unsubscribe("EVT001", q)
        assert bus.subscriber_count("EVT001") == 0

    def test_unsubscribe_nonexistent_queue_is_safe(self):
        bus = EventBus()
        bus.subscribe("EVT001")
        fake_queue: asyncio.Queue = asyncio.Queue()
        # Should not raise
        bus.unsubscribe("EVT001", fake_queue)

    def test_publish_delivers_to_all_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe("EVT001")
        q2 = bus.subscribe("EVT001")
        bus.publish("EVT001", "test_event", {"key": "value"})

        msg1 = q1.get_nowait()
        msg2 = q2.get_nowait()
        assert msg1 == {"event": "test_event", "data": {"key": "value"}}
        assert msg2 == {"event": "test_event", "data": {"key": "value"}}

    def test_publish_does_not_deliver_to_other_channels(self):
        bus = EventBus()
        q1 = bus.subscribe("EVT001")
        q2 = bus.subscribe("EVT002")
        bus.publish("EVT001", "test_event", {"x": 1})

        assert q1.get_nowait()["event"] == "test_event"
        assert q2.empty()

    def test_publish_none_data_defaults_to_empty_dict(self):
        bus = EventBus()
        q = bus.subscribe("EVT001")
        bus.publish("EVT001", "ping")
        msg = q.get_nowait()
        assert msg == {"event": "ping", "data": {}}

    def test_publish_drops_message_on_full_queue(self):
        bus = EventBus()
        q = bus.subscribe("EVT001")
        # Fill the queue (maxsize=64)
        for i in range(64):
            bus.publish("EVT001", "fill", {"i": i})
        assert q.full()
        # This should not raise — message is dropped
        bus.publish("EVT001", "overflow", {"dropped": True})
        # Queue still has 64 items, not 65
        assert q.qsize() == 64

    def test_publish_to_nonexistent_channel_is_noop(self):
        bus = EventBus()
        # Should not raise
        bus.publish("NOEXIST", "test", {"x": 1})

    def test_subscriber_count_zero_for_unknown_channel(self):
        bus = EventBus()
        assert bus.subscriber_count("UNKNOWN") == 0

    def test_multiple_channels_independent(self):
        bus = EventBus()
        q1 = bus.subscribe("A")
        q2 = bus.subscribe("B")
        bus.publish("A", "evt_a")
        bus.publish("B", "evt_b")
        assert q1.get_nowait()["event"] == "evt_a"
        assert q2.get_nowait()["event"] == "evt_b"


class TestSingleton:
    """Tests for module-level singleton helpers."""

    def test_get_event_bus_returns_same_instance(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_publish_event_delivers_via_singleton(self):
        bus = get_event_bus()
        q = bus.subscribe("SINGLETON_TEST")
        try:
            publish_event("SINGLETON_TEST", "hello", {"msg": "world"})
            msg = q.get_nowait()
            assert msg["event"] == "hello"
            assert msg["data"]["msg"] == "world"
        finally:
            bus.unsubscribe("SINGLETON_TEST", q)


class TestSSEEndpoint:
    """Tests for the SSE endpoint route registration."""

    def test_sse_route_is_registered(self):
        """Verify the SSE endpoint route exists in the app."""
        from app.main import app

        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/public/events/{code}/stream" in routes
