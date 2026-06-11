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

type RenderOpts = { callback?: (t: string) => void; 'error-callback'?: () => void };

let lastRenderOpts: RenderOpts | null = null;

describe('useHumanVerification', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastRenderOpts = null;
    // Mock window.turnstile
    type FakeTurnstile = {
      render: (
        el: HTMLElement,
        opts: RenderOpts
      ) => string;
      reset: (id?: string) => void;
      remove: (id: string) => void;
    };
    (window as unknown as { turnstile: FakeTurnstile }).turnstile = {
      render: vi.fn((_el, opts) => {
        lastRenderOpts = opts;
        // Asynchronously fire the callback with a fake token
        setTimeout(() => opts.callback?.('fake-token'), 0);
        return 'widget-id-1';
      }),
      // Real Turnstile re-runs the (invisible) challenge after reset and
      // invokes the original callback with a fresh token.
      reset: vi.fn(() => {
        setTimeout(() => lastRenderOpts?.callback?.('fresh-token'), 0);
      }),
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

  it('reverify resolves only after the re-run challenge completes', async () => {
    const { useHumanVerification } = await import('../useHumanVerification');
    const { result } = renderHook(() => useHumanVerification());
    await waitFor(() => expect(result.current.state).toBe('verified'));

    // Make reset inert so we control when the new token arrives.
    const turnstile = (window as unknown as { turnstile: { reset: ReturnType<typeof vi.fn> } })
      .turnstile;
    turnstile.reset.mockImplementation(() => {});

    let resolved = false;
    let promise!: Promise<void>;
    act(() => {
      promise = result.current.reverify().then(() => {
        resolved = true;
      });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    // Widget was reset but no new token yet -> contract says we must NOT
    // have resolved (the wrzdj_human cookie is not set yet).
    expect(resolved).toBe(false);
    expect(result.current.state).toBe('loading');

    // Complete the challenge.
    await act(async () => {
      lastRenderOpts?.callback?.('fresh-token');
      await promise;
    });
    expect(resolved).toBe(true);
    expect(result.current.state).toBe('verified');
  });

  it('reverify during an in-flight challenge waits instead of resetting it', async () => {
    const turnstile = (window as unknown as {
      turnstile: { render: ReturnType<typeof vi.fn>; reset: ReturnType<typeof vi.fn> };
    }).turnstile;
    // Challenge that never auto-completes.
    turnstile.render.mockImplementation((_el: HTMLElement, opts: RenderOpts) => {
      lastRenderOpts = opts;
      return 'widget-id-1';
    });

    const { useHumanVerification } = await import('../useHumanVerification');
    const { result } = renderHook(() => useHumanVerification());
    await waitFor(() => expect(result.current.state).toBe('loading'));

    let resolved = false;
    act(() => {
      void result.current.reverify().then(() => {
        resolved = true;
      });
    });
    // Mid-challenge reverify must not reset (it would restart the challenge).
    expect(turnstile.reset).not.toHaveBeenCalled();

    // The fallback-container path defers the actual widget render by up to
    // three animation frames — wait until the challenge is genuinely in
    // flight before completing it (otherwise the callback fire is a no-op).
    await waitFor(() => expect(lastRenderOpts).not.toBeNull());

    await act(async () => {
      lastRenderOpts?.callback?.('fake-token');
      await new Promise((r) => setTimeout(r, 0));
    });
    await waitFor(() => expect(result.current.state).toBe('verified'));
    await waitFor(() => expect(resolved).toBe(true));
  });

  it('reverify rejects with HumanVerificationFailedError when verification fails', async () => {
    const { useHumanVerification, HumanVerificationFailedError } = await import(
      '../useHumanVerification'
    );
    const { api } = await import('../api');
    const { result } = renderHook(() => useHumanVerification());
    await waitFor(() => expect(result.current.state).toBe('verified'));

    // The re-run challenge produces a token the server rejects.
    (api.verifyHuman as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ verified: false });

    let rejection: unknown = null;
    await act(async () => {
      await result.current.reverify().catch((err: unknown) => {
        rejection = err;
      });
    });
    expect(rejection).toBeInstanceOf(HumanVerificationFailedError);
    expect(result.current.state).toBe('failed');
  });
});
