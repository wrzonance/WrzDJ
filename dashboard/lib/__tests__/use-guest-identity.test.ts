import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

vi.mock('@thumbmarkjs/thumbmarkjs', () => ({
  getThumbmark: vi.fn().mockResolvedValue({ thumbmark: 'mock_hash_value', components: {} }),
}));

describe('useGuestIdentity (F6)', () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    mockFetch.mockReset();
    global.fetch = mockFetch as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('marks isReturning=false when server returns action=create', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ guest_id: 7, action: 'create' }),
      headers: { get: () => null },
    });

    // Dynamic import after mocks are set up — resets module-level cache
    const { useGuestIdentity } = await import('../use-guest-identity');
    const { result } = renderHook(() => useGuestIdentity());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.guestId).toBe(7);
    expect(result.current.isReturning).toBe(false);
  });

  it('marks isReturning=true when server returns action=cookie_hit', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ guest_id: 8, action: 'cookie_hit' }),
      headers: { get: () => null },
    });

    const { useGuestIdentity } = await import('../use-guest-identity');
    const { result } = renderHook(() => useGuestIdentity());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.guestId).toBe(8);
    expect(result.current.isReturning).toBe(true);
  });
});

describe('useGuestIdentity — reconcileHint and refresh()', () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    globalThis.fetch = mockFetch as unknown as typeof fetch;
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('exposes reconcileHint from server response', async () => {
    const { useGuestIdentity } = await import('../use-guest-identity');
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ guest_id: 42, action: 'create', reconcile_hint: true }),
    });

    const { result } = renderHook(() => useGuestIdentity());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.guestId).toBe(42);
    expect(result.current.reconcileHint).toBe(true);
  });

  it('refresh() clears module cache and re-fetches', async () => {
    const { useGuestIdentity } = await import('../use-guest-identity');
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ guest_id: 1, action: 'create', reconcile_hint: false }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ guest_id: 99, action: 'cookie_hit', reconcile_hint: false }),
      });

    const { result } = renderHook(() => useGuestIdentity());
    await waitFor(() => expect(result.current.guestId).toBe(1));

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.guestId).toBe(99);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('treats missing reconcile_hint field as false (backward-compat)', async () => {
    const { useGuestIdentity } = await import('../use-guest-identity');
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ guest_id: 7, action: 'create' }),
    });

    const { result } = renderHook(() => useGuestIdentity());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.reconcileHint).toBe(false);
  });

  it('refresh() surfaces fetch errors via state.error', async () => {
    const { useGuestIdentity } = await import('../use-guest-identity');
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ guest_id: 1, action: 'create', reconcile_hint: false }),
      })
      .mockRejectedValueOnce(new Error('Network error'));

    const { result } = renderHook(() => useGuestIdentity());
    await waitFor(() => expect(result.current.guestId).toBe(1));

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.error).toBe('Network error');
    expect(result.current.isLoading).toBe(false);
  });
});
