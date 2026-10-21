import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import type { NowPlayingInfo, PlayHistoryResponse, PublicBridgeStatus } from '@/lib/api';
import { useEventLiveStatus } from '../useEventLiveStatus';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const bridgeStatus = (connected: boolean): PublicBridgeStatus => ({
  connected,
  device_name: null,
  last_seen: null,
  circuit_breaker_state: connected ? 'closed' : null,
  buffer_size: connected ? 4 : null,
  plugin_id: connected ? 'deck-b' : null,
  deck_count: connected ? 2 : null,
  uptime_seconds: connected ? 20 : null,
});

const history = (title: string): PlayHistoryResponse => ({
  items: [{ title } as PlayHistoryResponse['items'][number]],
  total: 1,
});

describe('useEventLiveStatus', () => {
  afterEach(() => vi.restoreAllMocks());

  // Regression for baseline 57cfcdc6867f: a late join-code response from event A overwrote event B's live status.
  it('keeps the newest event live data when older endpoint responses finish last', async () => {
    const oldHistory = deferred<PlayHistoryResponse>();
    const oldNowPlaying = deferred<NowPlayingInfo | null>();
    const oldBridge = deferred<PublicBridgeStatus>();
    vi.spyOn(api, 'getPlayHistory')
      .mockReturnValueOnce(oldHistory.promise)
      .mockResolvedValue(history('Event B track'));
    vi.spyOn(api, 'getNowPlaying')
      .mockReturnValueOnce(oldNowPlaying.promise)
      .mockResolvedValue({ title: 'Event B track' } as NowPlayingInfo);
    vi.spyOn(api, 'getBridgeStatus')
      .mockReturnValueOnce(oldBridge.promise)
      .mockResolvedValue(bridgeStatus(true));

    const { result, rerender } = renderHook(
      ({ routeCode, joinCode }: { routeCode: string; joinCode: string | null }) =>
        useEventLiveStatus({ routeCode, joinCode }),
      { initialProps: { routeCode: 'EVENT-A', joinCode: 'JOIN-A' } },
    );
    await act(async () => Promise.resolve());

    rerender({ routeCode: 'EVENT-B', joinCode: 'JOIN-B' });
    await act(async () => Promise.resolve());
    expect(api.getPlayHistory).toHaveBeenLastCalledWith('JOIN-B');
    expect(result.current.playHistory[0]?.title).toBe('Event B track');
    expect(result.current.nowPlaying?.title).toBe('Event B track');
    expect(result.current.bridgeConnected).toBe(true);

    await act(async () => {
      oldHistory.resolve(history('Stale event A track'));
      oldNowPlaying.resolve({ title: 'Stale event A track' } as NowPlayingInfo);
      oldBridge.resolve(bridgeStatus(false));
      await Promise.all([oldHistory.promise, oldNowPlaying.promise, oldBridge.promise]);
    });

    expect(result.current.playHistory[0]?.title).toBe('Event B track');
    expect(result.current.nowPlaying?.title).toBe('Event B track');
    expect(result.current.bridgeConnected).toBe(true);
  });

  // Regression for baseline 57cfcdc6867f: an older HTTP poll must not replace a newer SSE bridge update.
  it('keeps a newer bridge event when an in-flight refresh finishes afterward', async () => {
    const historyRequest = deferred<PlayHistoryResponse>();
    const nowPlayingRequest = deferred<NowPlayingInfo | null>();
    const bridgeRequest = deferred<PublicBridgeStatus>();
    vi.spyOn(api, 'getPlayHistory').mockReturnValue(historyRequest.promise);
    vi.spyOn(api, 'getNowPlaying').mockReturnValue(nowPlayingRequest.promise);
    vi.spyOn(api, 'getBridgeStatus').mockReturnValue(bridgeRequest.promise);

    const { result } = renderHook(() => useEventLiveStatus({
      routeCode: 'EVENT-A',
      joinCode: 'JOIN-A',
    }));
    act(() => result.current.applyBridgeStatus(bridgeStatus(true), 'EVENT-A'));

    await act(async () => {
      historyRequest.resolve(history('Current track'));
      nowPlayingRequest.resolve({ title: 'Current track' } as NowPlayingInfo);
      bridgeRequest.resolve(bridgeStatus(false));
      await Promise.all([historyRequest.promise, nowPlayingRequest.promise, bridgeRequest.promise]);
    });

    expect(result.current.playHistory[0]?.title).toBe('Current track');
    expect(result.current.nowPlaying?.title).toBe('Current track');
    expect(result.current.bridgeConnected).toBe(true);
    expect(result.current.bridgeDetails?.pluginId).toBe('deck-b');
  });

  // Regression for baseline 57cfcdc6867f: a pending live refresh could commit after its owning page unmounted.
  it('ignores stale endpoint failures and completions after unmount', async () => {
    const historyRequest = deferred<PlayHistoryResponse>();
    const nowPlayingRequest = deferred<NowPlayingInfo | null>();
    const bridgeRequest = deferred<PublicBridgeStatus>();
    vi.spyOn(api, 'getPlayHistory').mockReturnValue(historyRequest.promise);
    vi.spyOn(api, 'getNowPlaying').mockReturnValue(nowPlayingRequest.promise);
    vi.spyOn(api, 'getBridgeStatus').mockReturnValue(bridgeRequest.promise);

    const { unmount } = renderHook(() => useEventLiveStatus({
      routeCode: 'EVENT-A',
      joinCode: 'JOIN-A',
    }));
    unmount();

    await act(async () => {
      historyRequest.reject(new Error('late history failure'));
      nowPlayingRequest.resolve(null);
      bridgeRequest.resolve(bridgeStatus(true));
      await Promise.all([
        historyRequest.promise.catch(() => undefined),
        nowPlayingRequest.promise,
        bridgeRequest.promise,
      ]);
    });
  });
});
