import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

vi.mock('../api', () => ({
  api: {
    getPublicSettings: vi.fn().mockResolvedValue({
      registration_enabled: true,
      turnstile_site_key: 'test-site-key',
    }),
    verifyHuman: vi.fn().mockResolvedValue({ verified: true, expires_in: 3600 }),
    // Default: cookie not yet established, fall through to Turnstile bootstrap.
    // Individual tests override this to verify the fast-path skip.
    getVerifyStatus: vi.fn().mockResolvedValue({ verified: false, expires_in: 0 }),
  },
  ApiError: class extends Error {
    status: number;
    constructor(m: string, s: number) {
      super(m);
      this.status = s;
    }
  },
}));

vi.mock('../turnstile', () => ({
  getTurnstileSiteKey: vi.fn().mockResolvedValue('test-site-key'),
  loadTurnstileScript: vi.fn().mockResolvedValue(undefined),
}));

describe('useHumanVerification', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock window.turnstile
    type FakeTurnstile = {
      render: (
        el: HTMLElement,
        opts: { callback?: (t: string) => void }
      ) => string;
      reset: (id?: string) => void;
      remove: (id: string) => void;
    };
    (window as unknown as { turnstile: FakeTurnstile }).turnstile = {
      render: vi.fn((_el, opts) => {
        // Asynchronously fire the callback with a fake token
        setTimeout(() => opts.callback?.('fake-token'), 0);
        return 'widget-id-1';
      }),
      reset: vi.fn(),
      remove: vi.fn(),
    };
  });

  it('starts in idle or loading state', async () => {
    const { useHumanVerification } = await import('../useHumanVerification');
    const { result } = renderHook(() => useHumanVerification());
    expect(['idle', 'loading']).toContain(result.current.state);
  });

  it('transitions to verified after successful bootstrap', async () => {
    const { useHumanVerification } = await import('../useHumanVerification');
    const { api } = await import('../api');
    const { result } = renderHook(() => useHumanVerification());

    await waitFor(
      () => {
        expect(result.current.state).toBe('verified');
      },
      { timeout: 2000 },
    );

    expect(api.verifyHuman).toHaveBeenCalledWith('fake-token');
  });

  it('reverify resets the widget and runs bootstrap again', async () => {
    const { useHumanVerification } = await import('../useHumanVerification');
    const { result } = renderHook(() => useHumanVerification());

    await waitFor(() => expect(result.current.state).toBe('verified'));

    await act(async () => {
      await result.current.reverify();
    });

    const turnstile = (window as unknown as { turnstile: { reset: ReturnType<typeof vi.fn> } }).turnstile;
    expect(turnstile.reset).toHaveBeenCalled();
  });

  it('treats empty site key as auto-verified (Turnstile disabled in dev)', async () => {
    const { getTurnstileSiteKey } = await import('../turnstile');
    (getTurnstileSiteKey as ReturnType<typeof vi.fn>).mockResolvedValueOnce('');

    const { useHumanVerification } = await import('../useHumanVerification');
    const { result } = renderHook(() => useHumanVerification());

    await waitFor(() => expect(result.current.state).toBe('verified'));

    // verifyHuman should NOT have been called (no token to send)
    const { api } = await import('../api');
    expect(api.verifyHuman).not.toHaveBeenCalled();
  });
});
