import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useEventStream } from '../use-event-stream';

vi.mock('../api/shared', () => ({ getApiUrl: () => '' }));

// Mock EventSource
class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners: Record<string, ((e: { data: string }) => void)[]> = {};

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (e: { data: string }) => void) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(handler);
  }

  close = vi.fn();

  // Test helpers
  simulateOpen() {
    this.readyState = 1;
    this.onopen?.();
  }

  simulateError() {
    this.onerror?.();
  }

  simulateEvent(type: string, data: object) {
    const handlers = this.listeners[type] || [];
    handlers.forEach((h) => h({ data: JSON.stringify(data) }));
  }

  simulateRawEvent(type: string, data: string) {
    const handlers = this.listeners[type] || [];
    handlers.forEach((handler) => handler({ data }));
  }

  static reset() {
    MockEventSource.instances = [];
  }

  static latest(): MockEventSource | undefined {
    return MockEventSource.instances[MockEventSource.instances.length - 1];
  }
}

beforeEach(() => {
  MockEventSource.reset();
  vi.stubGlobal('EventSource', MockEventSource);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe('useEventStream', () => {
  it('returns connected=false initially', () => {
    const { result } = renderHook(() =>
      useEventStream('EVT01', {}),
    );
    expect(result.current.connected).toBe(false);
  });

  it('connects to correct URL', () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', '');
    renderHook(() => useEventStream('EVT01', {}));
    const es = MockEventSource.latest();
    expect(es).toBeDefined();
    expect(es!.url).toBe('/api/public/events/EVT01/stream');
  });

  it('sets connected=true on open', () => {
    const { result } = renderHook(() =>
      useEventStream('EVT01', {}),
    );
    act(() => {
      MockEventSource.latest()!.simulateOpen();
    });
    expect(result.current.connected).toBe(true);
  });

  it('does not connect when eventCode is null', () => {
    renderHook(() => useEventStream(null, {}));
    expect(MockEventSource.instances).toHaveLength(0);
  });

  it('closes EventSource on unmount', () => {
    const { unmount } = renderHook(() =>
      useEventStream('EVT01', {}),
    );
    const es = MockEventSource.latest()!;
    unmount();
    expect(es.close).toHaveBeenCalled();
  });

  // Regression for baseline 57cfcdc6867f: queued callbacks from a previous event code stay scoped to that stream.
  it('ignores captured data and open callbacks from an old stream after changing event codes', () => {
    const oldHandler = vi.fn();
    const currentHandler = vi.fn();
    const { result, rerender } = renderHook(
      ({ code, onRequestCreated }) => useEventStream(code, { onRequestCreated }),
      { initialProps: { code: 'EVT01', onRequestCreated: oldHandler } },
    );
    const oldSource = MockEventSource.latest()!;
    const queuedRequestCreated = oldSource.listeners.request_created[0];
    const queuedOpen = oldSource.onopen!;

    rerender({ code: 'EVT02', onRequestCreated: currentHandler });
    const currentSource = MockEventSource.latest()!;

    act(() => {
      queuedRequestCreated({ data: JSON.stringify({ request_id: 2, title: 'Old', artist: 'Stream' }) });
      queuedOpen();
    });

    expect(oldHandler).not.toHaveBeenCalled();
    expect(currentHandler).not.toHaveBeenCalled();
    expect(result.current.connected).toBe(false);
    expect(currentSource.close).not.toHaveBeenCalled();
  });

  // Regression for baseline 57cfcdc6867f: an old connection error cannot clear or reconnect the replacement stream.
  it('ignores a captured error callback from an old stream after replacement', () => {
    const { result, rerender } = renderHook(
      ({ code }) => useEventStream(code, {}),
      { initialProps: { code: 'EVT01' } },
    );
    const oldSource = MockEventSource.latest()!;
    const queuedError = oldSource.onerror!;

    rerender({ code: 'EVT02' });
    const currentSource = MockEventSource.latest()!;
    act(() => currentSource.simulateOpen());
    expect(result.current.connected).toBe(true);

    act(() => queuedError());
    expect(result.current.connected).toBe(true);
    expect(currentSource.close).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(30_000));
    expect(MockEventSource.instances).toHaveLength(2);
  });

  // Regression for baseline 57cfcdc6867f: a callback already queued at cleanup cannot reconnect after unmount.
  it('does not reconnect when a captured error callback runs after unmount', () => {
    const { unmount } = renderHook(() => useEventStream('EVT01', {}));
    const source = MockEventSource.latest()!;
    const queuedError = source.onerror!;
    unmount();
    act(() => queuedError());
    act(() => vi.advanceTimersByTime(30_000));
    expect(MockEventSource.instances).toHaveLength(1);
  });

  it('sets connected=false on error', () => {
    const { result } = renderHook(() =>
      useEventStream('EVT01', {}),
    );
    act(() => {
      MockEventSource.latest()!.simulateOpen();
    });
    expect(result.current.connected).toBe(true);

    act(() => {
      MockEventSource.latest()!.simulateError();
    });
    expect(result.current.connected).toBe(false);
  });

  it('retries on error with exponential backoff', () => {
    renderHook(() => useEventStream('EVT01', {}));
    const first = MockEventSource.latest()!;

    // Trigger error
    act(() => {
      first.simulateError();
    });
    expect(MockEventSource.instances).toHaveLength(1);

    // Advance past 1st retry (1000ms)
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(MockEventSource.instances).toHaveLength(2);
  });

  it('retries indefinitely with capped backoff', () => {
    renderHook(() => useEventStream('EVT01', {}));

    // Simulate 5 consecutive errors — should keep retrying
    for (let i = 0; i < 5; i++) {
      act(() => {
        MockEventSource.latest()!.simulateError();
      });
      act(() => {
        vi.advanceTimersByTime(30_000); // Past max backoff cap
      });
    }

    // Should still create new connections (initial + 5 retries = 6)
    expect(MockEventSource.instances.length).toBe(6);
  });

  it('resets retry count on successful connection', () => {
    renderHook(() => useEventStream('EVT01', {}));

    // Fail twice
    act(() => { MockEventSource.latest()!.simulateError(); });
    act(() => { vi.advanceTimersByTime(1000); });
    act(() => { MockEventSource.latest()!.simulateError(); });
    act(() => { vi.advanceTimersByTime(2000); });

    // Now connect successfully — resets retry count
    act(() => { MockEventSource.latest()!.simulateOpen(); });

    // Next error should retry at initial delay (1s), not continued backoff
    act(() => { MockEventSource.latest()!.simulateError(); });
    const countBefore = MockEventSource.instances.length;
    act(() => { vi.advanceTimersByTime(1000); });
    expect(MockEventSource.instances.length).toBe(countBefore + 1);
  });

  describe('event handlers', () => {
    it('calls onRequestCreated on request_created event', () => {
      const onRequestCreated = vi.fn();
      renderHook(() =>
        useEventStream('EVT01', { onRequestCreated }),
      );
      const es = MockEventSource.latest()!;
      act(() => {
        es.simulateOpen();
        es.simulateEvent('request_created', { request_id: 1, title: 'Song', artist: 'DJ' });
      });
      expect(onRequestCreated).toHaveBeenCalledWith({ request_id: 1, title: 'Song', artist: 'DJ' });
    });

    it('calls onRequestStatusChanged', () => {
      const onRequestStatusChanged = vi.fn();
      renderHook(() =>
        useEventStream('EVT01', { onRequestStatusChanged }),
      );
      act(() => {
        MockEventSource.latest()!.simulateEvent('request_status_changed', { request_id: 1, status: 'accepted' });
      });
      expect(onRequestStatusChanged).toHaveBeenCalledWith({ request_id: 1, status: 'accepted' });
    });

    it('calls onNowPlayingChanged', () => {
      const onNowPlayingChanged = vi.fn();
      renderHook(() =>
        useEventStream('EVT01', { onNowPlayingChanged }),
      );
      act(() => {
        MockEventSource.latest()!.simulateEvent('now_playing_changed', { title: 'Track', artist: 'Art', source: 'stagelinq' });
      });
      expect(onNowPlayingChanged).toHaveBeenCalledWith({ title: 'Track', artist: 'Art', source: 'stagelinq' });
    });

    it('calls onRequestsBulkUpdate', () => {
      const onRequestsBulkUpdate = vi.fn();
      renderHook(() =>
        useEventStream('EVT01', { onRequestsBulkUpdate }),
      );
      act(() => {
        MockEventSource.latest()!.simulateEvent('requests_bulk_update', { action: 'accepted', count: 5 });
      });
      expect(onRequestsBulkUpdate).toHaveBeenCalledWith({ action: 'accepted', count: 5 });
    });

    it('calls onBridgeStatusChanged', () => {
      const onBridgeStatusChanged = vi.fn();
      renderHook(() =>
        useEventStream('EVT01', { onBridgeStatusChanged }),
      );
      act(() => {
        MockEventSource.latest()!.simulateEvent('bridge_status_changed', { connected: true, device_name: 'CDJ-3000' });
      });
      expect(onBridgeStatusChanged).toHaveBeenCalledWith({ connected: true, device_name: 'CDJ-3000' });
    });

    it('ignores malformed but valid JSON for every event and keeps handling later frames', () => {
      const handlers = {
        onRequestCreated: vi.fn(),
        onRequestStatusChanged: vi.fn(),
        onNowPlayingChanged: vi.fn(),
        onRequestsBulkUpdate: vi.fn(),
        onBridgeStatusChanged: vi.fn(),
      };
      renderHook(() => useEventStream('EVT01', handlers));
      const es = MockEventSource.latest()!;

      const malformedFrames = [
        ['request_created', { request_id: '1', title: 'Song', artist: 'DJ' }],
        ['request_status_changed', { request_id: 1, status: ['accepted'] }],
        ['request_status_changed', { request_id: 2, status: 'cancelled' }],
        ['now_playing_changed', { title: 'Track', artist: 'Artist', source: null }],
        ['requests_bulk_update', { action: ['accepted'], count: 2 }],
        ['bridge_status_changed', { connected: 'true', device_name: 'CDJ-3000' }],
      ] as const;

      const validFrames = [
        ['request_created', { request_id: 1, title: 'Song', artist: 'DJ' }],
        ['request_status_changed', { request_id: 1, status: 'accepted' }],
        ['now_playing_changed', { title: 'Track', artist: 'Artist', source: 'bridge' }],
        ['requests_bulk_update', { action: 'accepted', count: 2 }],
        ['bridge_status_changed', { connected: true, device_name: null }],
      ] as const;

      act(() => {
        for (const [type, data] of malformedFrames) {
          es.simulateRawEvent(type, JSON.stringify(data));
        }
      });
      for (const handler of Object.values(handlers)) {
        expect(handler).not.toHaveBeenCalled();
      }

      act(() => {
        for (const [type, data] of validFrames) {
          es.simulateRawEvent(type, JSON.stringify(data));
        }
      });
      expect(handlers.onRequestCreated).toHaveBeenCalledWith(validFrames[0][1]);
      expect(handlers.onRequestStatusChanged).toHaveBeenCalledWith(validFrames[1][1]);
      expect(handlers.onNowPlayingChanged).toHaveBeenCalledWith(validFrames[2][1]);
      expect(handlers.onRequestsBulkUpdate).toHaveBeenCalledWith(validFrames[3][1]);
      expect(handlers.onBridgeStatusChanged).toHaveBeenCalledWith(validFrames[4][1]);
    });

    it('ignores missing handlers gracefully', () => {
      renderHook(() => useEventStream('EVT01', {}));
      // Should not throw
      act(() => {
        MockEventSource.latest()!.simulateEvent('request_created', { request_id: 1 });
        MockEventSource.latest()!.simulateEvent('now_playing_changed', { title: 'X' });
      });
    });

    // Regression for baseline 57cfcdc6867f: malformed frames must not throw from EventSource callbacks.
    it('ignores malformed event data without breaking later events', () => {
      const onRequestCreated = vi.fn();
      renderHook(() => useEventStream('EVT01', { onRequestCreated }));
      const es = MockEventSource.latest()!;

      expect(() => {
        act(() => {
          es.simulateRawEvent('request_created', '{invalid json');
          es.simulateEvent('request_created', { request_id: 2, title: 'Song', artist: 'DJ' });
        });
      }).not.toThrow();
      expect(onRequestCreated).toHaveBeenCalledOnce();
      expect(onRequestCreated).toHaveBeenCalledWith({ request_id: 2, title: 'Song', artist: 'DJ' });
    });
  });

  it('registers all five event listeners', () => {
    renderHook(() => useEventStream('EVT01', {}));
    const es = MockEventSource.latest()!;
    const eventTypes = Object.keys(es.listeners);
    expect(eventTypes).toContain('request_created');
    expect(eventTypes).toContain('request_status_changed');
    expect(eventTypes).toContain('now_playing_changed');
    expect(eventTypes).toContain('requests_bulk_update');
    expect(eventTypes).toContain('bridge_status_changed');
  });
});
