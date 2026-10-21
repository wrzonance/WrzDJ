"""Tests for the in-memory event bus (SSE pub/sub)."""

import asyncio
from threading import Event, Thread

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

    def test_queue_full_log_escapes_dynamic_values(self, caplog):
        bus = EventBus()
        event_code = "EVT001\nforged channel"
        queue = bus.subscribe(event_code)
        for _ in range(queue.maxsize):
            queue.put_nowait({"event": "existing", "data": {}})

        bus.publish(event_code, "track\nforged event")

        assert "EVT001 forged channel" in caplog.text
        assert "track forged event" in caplog.text
        assert "\nforged channel" not in caplog.text
        assert "\nforged event" not in caplog.text

    def test_publish_does_not_deliver_to_other_channels(self):
        bus = EventBus()
        q1 = bus.subscribe("EVT001")
        q2 = bus.subscribe("EVT002")
        bus.publish("EVT001", "test_event", {"x": 1})

        assert q1.get_nowait()["event"] == "test_event"
        assert q2.empty()

    def test_publish_from_worker_thread_wakes_async_subscriber(self):
        loop = asyncio.new_event_loop()
        loop.set_debug(True)
        bus = EventBus()

        async def subscribe_and_wait():
            queue = bus.subscribe("EVT001")
            waiting = asyncio.create_task(queue.get())
            await asyncio.sleep(0)  # Let queue.get bind to this loop before the worker publishes.
            return queue, waiting

        queue, waiting = loop.run_until_complete(subscribe_and_wait())
        publish_errors: list[BaseException] = []
        thread_safe_callbacks: list[object] = []
        call_soon_threadsafe = loop.call_soon_threadsafe

        def record_thread_safe_callback(callback, *args, **kwargs):
            thread_safe_callbacks.append(callback)
            return call_soon_threadsafe(callback, *args, **kwargs)

        loop.call_soon_threadsafe = record_thread_safe_callback

        def publish_from_worker():
            try:
                bus.publish("EVT001", "worker_event", {"source": "thread"})
            except BaseException as error:
                publish_errors.append(error)

        publisher = Thread(target=publish_from_worker)
        publisher.start()
        publisher.join(timeout=1)
        try:
            assert not publisher.is_alive(), "publisher thread did not finish"
            assert thread_safe_callbacks, (
                "cross-thread publish must wake the subscriber loop safely"
            )
            message = loop.run_until_complete(asyncio.wait_for(waiting, timeout=1))
            assert message == {"event": "worker_event", "data": {"source": "thread"}}
            assert not publish_errors
        finally:
            bus.unsubscribe("EVT001", queue)
            if not waiting.done():
                waiting.cancel()
                loop.run_until_complete(asyncio.gather(waiting, return_exceptions=True))
            loop.close()

    def test_sync_subscribe_binds_to_loop_when_async_consumer_starts(self):
        loop = asyncio.new_event_loop()
        loop.set_debug(True)
        bus = EventBus()
        queue = bus.subscribe("EVT001")

        async def start_consumer():
            waiting = asyncio.create_task(queue.get())
            await asyncio.sleep(0)
            return waiting

        waiting = loop.run_until_complete(start_consumer())
        thread_safe_callbacks: list[object] = []
        call_soon_threadsafe = loop.call_soon_threadsafe

        def record_thread_safe_callback(callback, *args, **kwargs):
            thread_safe_callbacks.append(callback)
            return call_soon_threadsafe(callback, *args, **kwargs)

        loop.call_soon_threadsafe = record_thread_safe_callback
        publisher = Thread(target=bus.publish, args=("EVT001", "worker_event"))
        publisher.start()
        publisher.join(timeout=1)
        try:
            assert not publisher.is_alive(), "publisher thread did not finish"
            assert thread_safe_callbacks, "async consumption must bind the subscriber's loop"
            assert loop.run_until_complete(asyncio.wait_for(waiting, timeout=1)) == {
                "event": "worker_event",
                "data": {},
            }
        finally:
            bus.unsubscribe("EVT001", queue)
            if not waiting.done():
                waiting.cancel()
                loop.run_until_complete(asyncio.gather(waiting, return_exceptions=True))
            loop.close()

    def test_publish_skips_sync_subscriber_unsubscribed_after_snapshot(self):
        bus = EventBus()
        removed_queue = bus.subscribe("EVT001")
        retained_queue = bus.subscribe("EVT001")
        delivery_started = Event()
        continue_delivery = Event()
        deliver = bus._deliver

        def pause_before_delivery(event_code, queue, subscriber_loop, message):
            if queue is removed_queue:
                delivery_started.set()
                assert continue_delivery.wait(timeout=1)
            deliver(event_code, queue, subscriber_loop, message)

        bus._deliver = pause_before_delivery
        publisher = Thread(target=bus.publish, args=("EVT001", "race_event"))
        publisher.start()
        try:
            assert delivery_started.wait(timeout=1), "publisher did not snapshot subscribers"
            bus.unsubscribe("EVT001", removed_queue)
            continue_delivery.set()
            publisher.join(timeout=1)

            assert not publisher.is_alive(), "publisher thread did not finish"
            assert removed_queue.empty()
            assert retained_queue.get_nowait() == {"event": "race_event", "data": {}}
        finally:
            continue_delivery.set()
            publisher.join(timeout=1)
            bus.unsubscribe("EVT001", retained_queue)

    def test_publish_hands_off_when_async_consumer_binds_after_snapshot(self):
        loop = asyncio.new_event_loop()
        loop.set_debug(True)
        bus = EventBus()
        subscriber_bound = asyncio.Event()
        bind_loop = bus._bind_subscriber_loop

        def signal_binding(event_code, queue, subscriber_loop):
            bind_loop(event_code, queue, subscriber_loop)
            subscriber_bound.set()

        bus._bind_subscriber_loop = signal_binding
        queue = bus.subscribe("EVT001")
        delivery_started = Event()
        continue_delivery = Event()
        deliver = bus._deliver

        def pause_before_delivery(event_code, target_queue, subscriber_loop, message):
            delivery_started.set()
            assert continue_delivery.wait(timeout=1)
            deliver(event_code, target_queue, subscriber_loop, message)

        bus._deliver = pause_before_delivery
        publisher = Thread(target=bus.publish, args=("EVT001", "race_event"))
        publisher.start()
        waiting = None
        try:
            assert delivery_started.wait(timeout=1), "publisher did not snapshot subscribers"

            async def start_consumer():
                nonlocal waiting
                waiting = asyncio.create_task(queue.get())
                await asyncio.wait_for(subscriber_bound.wait(), timeout=1)

            loop.run_until_complete(start_consumer())
            continue_delivery.set()
            publisher.join(timeout=1)

            assert not publisher.is_alive(), "publisher thread did not finish"
            assert loop.run_until_complete(asyncio.wait_for(waiting, timeout=1)) == {
                "event": "race_event",
                "data": {},
            }
        finally:
            continue_delivery.set()
            publisher.join(timeout=1)
            bus.unsubscribe("EVT001", queue)
            if waiting is not None and not waiting.done():
                waiting.cancel()
                loop.run_until_complete(asyncio.gather(waiting, return_exceptions=True))
            loop.close()

    def test_unsubscribe_discards_cross_thread_delivery_already_queued_on_loop(self):
        loop = asyncio.new_event_loop()
        bus = EventBus()

        async def subscribe_and_wait():
            queue = bus.subscribe("EVT001")
            waiting = asyncio.create_task(queue.get())
            await asyncio.sleep(0)
            return queue, waiting

        queue, waiting = loop.run_until_complete(subscribe_and_wait())
        publisher = Thread(target=bus.publish, args=("EVT001", "stale_event"))
        publisher.start()
        publisher.join(timeout=1)
        try:
            assert not publisher.is_alive(), "publisher thread did not finish"
            bus.unsubscribe("EVT001", queue)
            loop.run_until_complete(asyncio.sleep(0))

            assert queue.empty()
            assert bus.subscriber_count("EVT001") == 0
        finally:
            if not waiting.done():
                waiting.cancel()
                loop.run_until_complete(asyncio.gather(waiting, return_exceptions=True))
            loop.close()

    def test_publish_removes_subscriber_whose_loop_has_closed(self):
        loop = asyncio.new_event_loop()
        bus = EventBus()

        async def subscribe():
            return bus.subscribe("EVT001")

        queue = loop.run_until_complete(subscribe())
        loop.close()

        bus.publish("EVT001", "after_loop_close")

        assert bus.subscriber_count("EVT001") == 0
        assert queue.empty()

    def test_publish_reaches_subscribers_owned_by_multiple_event_loops(self):
        loops = [asyncio.new_event_loop(), asyncio.new_event_loop()]
        bus = EventBus()
        queues: list[asyncio.Queue] = []

        for loop in loops:

            async def subscribe():
                return bus.subscribe("EVT001")

            queues.append(loop.run_until_complete(subscribe()))

        publisher = Thread(target=bus.publish, args=("EVT001", "multi_loop"))
        publisher.start()
        publisher.join(timeout=1)
        try:
            assert not publisher.is_alive(), "publisher thread did not finish"
            messages = [
                loop.run_until_complete(asyncio.wait_for(queue.get(), timeout=1))
                for loop, queue in zip(loops, queues, strict=True)
            ]
            assert messages == [
                {"event": "multi_loop", "data": {}},
                {"event": "multi_loop", "data": {}},
            ]
        finally:
            for loop, queue in zip(loops, queues, strict=True):
                bus.unsubscribe("EVT001", queue)
                loop.close()

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

    def test_cross_thread_publish_drops_when_async_queue_is_full(self):
        loop = asyncio.new_event_loop()
        bus = EventBus()

        async def subscribe():
            return bus.subscribe("EVT001")

        queue = loop.run_until_complete(subscribe())
        publisher = Thread(
            target=lambda: [bus.publish("EVT001", "fill", {"i": index}) for index in range(65)]
        )
        publisher.start()
        publisher.join(timeout=1)
        try:
            assert not publisher.is_alive(), "publisher thread did not finish"
            loop.run_until_complete(asyncio.sleep(0))

            assert queue.qsize() == 64
            assert queue.get_nowait() == {"event": "fill", "data": {"i": 0}}
        finally:
            bus.unsubscribe("EVT001", queue)
            loop.close()

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

    def test_publish_event_reaches_subscribers_on_multiple_loops(self):
        bus = get_event_bus()
        channel = f"SINGLETON_MULTI_LOOP_{id(bus)}"
        loops = [asyncio.new_event_loop(), asyncio.new_event_loop()]
        queues: list[asyncio.Queue] = []

        for loop in loops:

            async def subscribe():
                return bus.subscribe(channel)

            queues.append(loop.run_until_complete(subscribe()))

        publisher = Thread(target=publish_event, args=(channel, "threaded_hello", {"ok": True}))
        publisher.start()
        publisher.join(timeout=1)
        try:
            assert not publisher.is_alive(), "publisher thread did not finish"
            messages = [
                loop.run_until_complete(asyncio.wait_for(queue.get(), timeout=1))
                for loop, queue in zip(loops, queues, strict=True)
            ]
            assert messages == [
                {"event": "threaded_hello", "data": {"ok": True}},
                {"event": "threaded_hello", "data": {"ok": True}},
            ]
        finally:
            for loop, queue in zip(loops, queues, strict=True):
                bus.unsubscribe(channel, queue)
                loop.close()


class TestSSEEndpoint:
    """Tests for the SSE endpoint route registration."""

    def test_sse_route_is_registered(self):
        """Verify the SSE endpoint route exists on the SSE router."""
        from app.api.sse import router

        routes = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/events/{code}/stream" in routes
