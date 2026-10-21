import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { usePollingLoop } from '../use-polling-loop';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('usePollingLoop', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not start another load while the current poll is still pending', async () => {
    vi.useFakeTimers();
    const firstPoll = deferred<boolean>();
    const load = vi.fn(() => firstPoll.promise);
    const { unmount } = renderHook(() => usePollingLoop(true, load, 1_000));

    expect(load).toHaveBeenCalledOnce();

    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    expect(load).toHaveBeenCalledOnce();

    await act(async () => {
      firstPoll.resolve(true);
      await firstPoll.promise;
    });
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(load).toHaveBeenCalledTimes(2);

    unmount();
  });
});
