import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, type CollectEventPreview } from '@/lib/api';
import { useCollectPolling } from '../useCollectPolling';

const mocks = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => mocks }));

const event = {
  code: 'PARTY7',
  name: 'Party',
  banner_filename: null,
  banner_url: null,
  banner_colors: null,
  submission_cap_per_guest: 5,
  registration_enabled: false,
  phase: 'pre_announce',
  collection_opens_at: null,
  live_starts_at: null,
  expires_at: '2030-01-01T00:00:00Z',
} satisfies CollectEventPreview;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

describe('useCollectPolling visibility resume', () => {
  let priorVisibilityDescriptor: PropertyDescriptor | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    priorVisibilityDescriptor = Object.getOwnPropertyDescriptor(document, 'visibilityState');
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    vi.spyOn(api, 'getCollectEvent').mockResolvedValue(event);
  });

  afterEach(() => {
    if (priorVisibilityDescriptor) {
      Object.defineProperty(document, 'visibilityState', priorVisibilityDescriptor);
    } else {
      Reflect.deleteProperty(document, 'visibilityState');
    }
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('replaces the pending timer when a hidden tab resumes instead of creating two poll chains', async () => {
    const reverify = vi.fn();
    renderHook(() => useCollectPolling({
      code: 'PARTY7',
      tab: 'trending',
      displayLimit: 10,
      gateComplete: true,
      emailVerified: false,
      humanState: 'unverified',
      reverify,
    }));

    await act(async () => Promise.resolve());
    expect(api.getCollectEvent).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
    });
    expect(api.getCollectEvent).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(1);

    await act(async () => vi.advanceTimersByTimeAsync(5000));

    expect(api.getCollectEvent).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('coalesces a visibility refresh while a request is already in flight', async () => {
    const pending = deferred<CollectEventPreview>();
    const getEvent = vi.spyOn(api, 'getCollectEvent')
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValue(event);
    const reverify = vi.fn();
    renderHook(() => useCollectPolling({
      code: 'PARTY7',
      tab: 'trending',
      displayLimit: 10,
      gateComplete: true,
      emailVerified: false,
      humanState: 'unverified',
      reverify,
    }));
    expect(getEvent).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    act(() => document.dispatchEvent(new Event('visibilitychange')));
    expect(getEvent).toHaveBeenCalledTimes(1);

    await act(async () => {
      pending.resolve(event);
      await pending.promise;
      await Promise.resolve();
    });

    expect(getEvent).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(1);
  });

  // Regression for baseline 57cfcdc6867f: non-Error polling rejections yielded an undefined page error.
  it('shows a safe fallback for non-Error failures and clears it after polling recovers', async () => {
    vi.spyOn(api, 'getCollectEvent')
      .mockRejectedValueOnce('offline')
      .mockResolvedValue(event);
    const reverify = vi.fn();
    const { result } = renderHook(() => useCollectPolling({
      code: 'PARTY7',
      tab: 'trending',
      displayLimit: 10,
      gateComplete: true,
      emailVerified: false,
      humanState: 'unverified',
      reverify,
    }));

    await act(async () => Promise.resolve());
    expect(result.current.error).toBe('Unable to load event data. Please try again.');

    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(result.current.error).toBeNull();
    expect(result.current.event).toEqual(event);
  });
});
