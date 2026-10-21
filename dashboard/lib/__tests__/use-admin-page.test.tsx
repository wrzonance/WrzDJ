import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAdminPage } from '../use-admin-page';

const { hasSeenPage, startOnboarding } = vi.hoisted(() => ({
  hasSeenPage: vi.fn(() => false),
  startOnboarding: vi.fn(),
}));

vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({
    hasSeenPage,
    startOnboarding,
    onboardingActive: false,
  }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useAdminPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('loads and reloads data, clearing a previous error on success', async () => {
    const firstLoad = deferred<{ value: string }>();
    const reloadResult = deferred<{ value: string }>();
    const loader = vi.fn()
      .mockReturnValueOnce(firstLoad.promise)
      .mockReturnValueOnce(reloadResult.promise);
    const { result } = renderHook(() => useAdminPage({ pageId: 'users', loader }));

    expect(result.current.loading).toBe(true);
    await act(async () => firstLoad.resolve({ value: 'initial' }));
    expect(result.current.data).toEqual({ value: 'initial' });
    expect(result.current.error).toBe('');
    expect(result.current.loading).toBe(false);

    let reload!: Promise<void>;
    act(() => { reload = result.current.reload(); });
    expect(result.current.loading).toBe(true);
    await act(async () => reloadResult.resolve({ value: 'refreshed' }));
    await reload;
    expect(result.current.data).toEqual({ value: 'refreshed' });
    expect(result.current.error).toBe('');
    expect(result.current.loading).toBe(false);
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('maps a loader failure through onError', async () => {
    const failure = new Error('private detail');
    const loader = vi.fn().mockRejectedValue(failure);
    const onError = vi.fn((error: unknown) =>
      error instanceof Error ? 'Could not load users' : 'Unknown failure',
    );
    const { result } = renderHook(() => useAdminPage({
      pageId: 'users',
      loader,
      onError,
    }));

    await act(async () => {});

    expect(onError).toHaveBeenCalledWith(failure);
    expect(result.current.error).toBe('Could not load users');
    expect(result.current.loading).toBe(false);
  });

  // Regression for baseline 57cfcdc6867f: an older request must not replace a newer reload.
  it('keeps the newest reload result when an older request resolves later', async () => {
    const firstLoad = deferred<{ value: string }>();
    const secondLoad = deferred<{ value: string }>();
    const loader = vi.fn()
      .mockReturnValueOnce(firstLoad.promise)
      .mockReturnValueOnce(secondLoad.promise);
    const { result } = renderHook(() => useAdminPage({ pageId: 'users', loader }));

    let reload!: Promise<void>;
    act(() => { reload = result.current.reload(); });
    await act(async () => secondLoad.resolve({ value: 'newest' }));
    await reload;
    expect(result.current.data).toEqual({ value: 'newest' });

    await act(async () => firstLoad.resolve({ value: 'stale' }));
    expect(result.current.data).toEqual({ value: 'newest' });
  });

  it('cancels and reschedules onboarding when loaded data changes', async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useAdminPage({
      pageId: 'users',
      loader: async () => ['first'],
    }));
    await act(async () => {});

    act(() => { result.current.setData(['updated']); });
    act(() => { vi.advanceTimersByTime(499); });
    expect(startOnboarding).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(1); });
    expect(startOnboarding).toHaveBeenCalledOnce();
    expect(startOnboarding).toHaveBeenCalledWith('users');
  });

  it('cancels a pending onboarding timer on unmount', async () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useAdminPage({
      pageId: 'users',
      loader: async () => ['loaded'],
    }));
    await act(async () => {});

    unmount();
    act(() => { vi.advanceTimersByTime(500); });
    expect(startOnboarding).not.toHaveBeenCalled();
  });
});
