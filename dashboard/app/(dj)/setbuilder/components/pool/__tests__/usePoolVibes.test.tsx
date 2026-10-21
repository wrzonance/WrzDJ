import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import type { PoolVibesState, TrackVibeState } from '@/lib/api/types';
import { usePoolVibes } from '../usePoolVibes';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

describe('usePoolVibes set changes', () => {
  it('discards a vibe load that completes after switching to another set', async () => {
    const response = deferred<PoolVibesState>();
    vi.spyOn(api, 'getPoolVibes').mockReturnValue(response.promise);
    const setToast = vi.fn();
    const { result, rerender } = renderHook(
      ({ setId }) => usePoolVibes(setId, setToast),
      { initialProps: { setId: 1 } },
    );

    act(() => result.current.toggleVibes());
    expect(api.getPoolVibes).toHaveBeenCalledWith(1);

    rerender({ setId: 2 });
    await act(async () => {
      response.resolve({ tracks: [{ pool_track_id: 7 } as TrackVibeState] } as PoolVibesState);
      await response.promise;
    });

    expect(result.current.vibes.size).toBe(0);
    expect(result.current.vibesBusy).toBe(false);
    expect(setToast).not.toHaveBeenCalled();
  });

  it('discards analysis and vote responses from the previous set', async () => {
    const analysis = deferred<{
      vibes: PoolVibesState;
      enriched: number;
      cached: number;
      failed: number;
      llm_calls: number;
    }>();
    const vote = deferred<PoolVibesState>();
    vi.spyOn(api, 'enrichPoolVibes').mockReturnValue(analysis.promise);
    vi.spyOn(api, 'agreePoolVibe').mockReturnValue(vote.promise);
    const setToast = vi.fn();
    const { result, rerender } = renderHook(
      ({ setId }) => usePoolVibes(setId, setToast),
      { initialProps: { setId: 1 } },
    );

    let analyze: Promise<void>;
    act(() => { analyze = result.current.analyzeVibes(); });
    expect(api.enrichPoolVibes).toHaveBeenCalledWith(1);
    rerender({ setId: 2 });
    await act(async () => {
      analysis.resolve({
        vibes: { tracks: [{ pool_track_id: 7 } as TrackVibeState] } as PoolVibesState,
        enriched: 1,
        cached: 0,
        failed: 0,
        llm_calls: 1,
      });
      await analyze!;
    });
    expect(result.current.vibes.size).toBe(0);
    expect(setToast).not.toHaveBeenCalled();

    let agree: Promise<boolean>;
    act(() => { agree = result.current.agreeVibe(8); });
    expect(api.agreePoolVibe).toHaveBeenCalledWith(2, 8);
    rerender({ setId: 3 });
    await act(async () => {
      vote.resolve({ tracks: [{ pool_track_id: 8 } as TrackVibeState] } as PoolVibesState);
      await agree!;
    });
    expect(result.current.vibes.size).toBe(0);
    expect(setToast).not.toHaveBeenCalled();
  });
});
