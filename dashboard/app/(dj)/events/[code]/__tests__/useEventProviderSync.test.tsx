import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '@/lib/api';
import { useEventProviderSync } from '../useEventProviderSync';

describe('useEventProviderSync Tidal device flow', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('opens the device flow and clears both polling timers when the hook unmounts', async () => {
    vi.spyOn(api, 'startTidalAuth').mockResolvedValue({
      verification_url: 'https://tidal.example/device', user_code: 'ABCD-EFGH', message: 'Authorize',
    });
    const { result, unmount } = renderHook(() => useEventProviderSync({
      event: null,
      requests: [],
      setAllRequests: vi.fn(),
      refetchRequests: vi.fn(),
      setActionError: vi.fn(),
    }));

    await act(async () => result.current.handleConnectTidal());

    expect(result.current.showTidalLogin).toBe(true);
    expect(result.current.tidalLoginUrl).toBe('https://tidal.example/device');
    expect(result.current.tidalLoginCode).toBe('ABCD-EFGH');
    expect(result.current.tidalLoginPolling).toBe(true);
    expect(vi.getTimerCount()).toBe(2);

    unmount();

    expect(vi.getTimerCount()).toBe(0);
  });

  it('ends polling and publishes the linked status when authorization completes', async () => {
    vi.spyOn(api, 'startTidalAuth').mockResolvedValue({
      verification_url: 'https://tidal.example/device', user_code: 'ABCD-EFGH', message: 'Authorize',
    });
    vi.spyOn(api, 'checkTidalAuth').mockResolvedValue({ complete: true, user_id: 'listener-7' });
    const { result } = renderHook(() => useEventProviderSync({
      event: null,
      requests: [],
      setAllRequests: vi.fn(),
      refetchRequests: vi.fn(),
      setActionError: vi.fn(),
    }));
    await act(async () => result.current.handleConnectTidal());

    await act(async () => vi.advanceTimersByTimeAsync(2000));

    expect(api.checkTidalAuth).toHaveBeenCalledOnce();
    expect(result.current.tidalLoginPolling).toBe(false);
    expect(result.current.showTidalLogin).toBe(false);
    expect(result.current.tidalStatus).toEqual({
      linked: true, user_id: 'listener-7', expires_at: null, integration_enabled: true,
    });
    expect(vi.getTimerCount()).toBe(0);
  });

  it('keeps the device flow open for a transient poll failure, but stops on provider rejection', async () => {
    const setActionError = vi.fn();
    vi.spyOn(api, 'startTidalAuth').mockResolvedValue({
      verification_url: 'https://tidal.example/device', user_code: 'ABCD-EFGH', message: 'Authorize',
    });
    const check = vi.spyOn(api, 'checkTidalAuth')
      .mockRejectedValueOnce(new ApiError('Temporary outage', 503))
      .mockResolvedValueOnce({ complete: false, error: 'Authorization expired' });
    const { result } = renderHook(() => useEventProviderSync({
      event: null,
      requests: [],
      setAllRequests: vi.fn(),
      refetchRequests: vi.fn(),
      setActionError,
    }));
    await act(async () => result.current.handleConnectTidal());

    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(check).toHaveBeenCalledTimes(1);
    expect(result.current.tidalLoginPolling).toBe(true);

    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(check).toHaveBeenCalledTimes(2);
    expect(result.current.tidalLoginPolling).toBe(false);
    expect(setActionError).toHaveBeenCalledWith('Tidal login failed: Authorization expired');
    expect(vi.getTimerCount()).toBe(0);
  });
});
