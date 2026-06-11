'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from './api';
import { getTurnstileSiteKey, loadTurnstileScript } from './turnstile';

export type HumanVerificationState =
  | 'idle'
  | 'loading'
  | 'verified'
  | 'challenge'
  | 'failed';

/**
 * Terminal client-side verification failure: the Turnstile widget errored or
 * the server rejected the token. `reverify()` rejects with this so callers
 * (via withHumanRetry) can distinguish "bot check failed" from feature-level
 * errors instead of silently degrading. See issue #419.
 */
export class HumanVerificationFailedError extends Error {
  constructor() {
    super('human_verification_failed');
    this.name = 'HumanVerificationFailedError';
  }
}

export interface UseHumanVerification {
  state: HumanVerificationState;
  ensureVerified: () => Promise<void>;
  reverify: () => Promise<void>;
  retry: () => void;
  widgetContainerRef: React.RefObject<HTMLDivElement | null>;
}

interface VerificationWaiter {
  resolve: () => void;
  reject: (err: Error) => void;
}

/**
 * Owns the human-verification state machine for the page.
 *
 * On mount, probes /api/public/guest/verify-status to short-circuit Turnstile
 * when the visitor already has a valid wrzdj_human cookie. When no valid
 * cookie exists, renders the Turnstile widget into the page-supplied
 * widget container (provided by HumanVerificationOverlay). Cloudflare
 * escalation from invisible to visible challenge flips state to 'challenge'
 * via the before-interactive-callback so the overlay can reveal the widget.
 *
 * Contract (relied on by withHumanRetry in lib/api.ts): `reverify()` resolves
 * only once verification has completed and the wrzdj_human cookie has been
 * issued; it rejects with HumanVerificationFailedError on terminal failure.
 * It never resets a challenge that is already in flight.
 */
export function useHumanVerification(): UseHumanVerification {
  const [state, setState] = useState<HumanVerificationState>('idle');
  const widgetContainerRef = useRef<HTMLDivElement | null>(null);
  const fallbackContainerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const waitersRef = useRef<VerificationWaiter[]>([]);
  const mountedRef = useRef(true);
  const retryCountRef = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;
  /* Synchronous re-entry guard for reverify(): stateRef lags one render cycle
     behind setState, so two reverify() calls in the same microtask turn could
     both see a stale non-loading state and double-reset the widget. */
  const reverifyInFlightRef = useRef(false);

  const flushVerified = useCallback(() => {
    reverifyInFlightRef.current = false;
    const waiters = waitersRef.current;
    waitersRef.current = [];
    waiters.forEach(({ resolve }) => resolve());
  }, []);

  const flushFailed = useCallback(() => {
    reverifyInFlightRef.current = false;
    const waiters = waitersRef.current;
    waitersRef.current = [];
    waiters.forEach(({ reject }) => reject(new HumanVerificationFailedError()));
  }, []);

  const waitForVerified = useCallback(
    () =>
      new Promise<void>((resolve, reject) => {
        waitersRef.current = [...waitersRef.current, { resolve, reject }];
      }),
    [],
  );

  const submitToken = useCallback(
    async (token: string) => {
      try {
        const result = await api.verifyHuman(token);
        if (!mountedRef.current) return;
        if (result.verified) {
          setState('verified');
          flushVerified();
        } else {
          setState('failed');
          flushFailed();
        }
      } catch {
        if (mountedRef.current) setState('failed');
        flushFailed();
      }
    },
    [flushVerified, flushFailed],
  );

  const renderWidget = useCallback(async () => {
    if (!mountedRef.current) return;
    setState('loading');
    const sitekey = await getTurnstileSiteKey();
    if (!mountedRef.current) return;
    if (!sitekey) {
      // Dev / Turnstile-disabled — treat as verified
      setState('verified');
      flushVerified();
      return;
    }
    await loadTurnstileScript();
    if (!mountedRef.current || !window.turnstile) return;

    let container = widgetContainerRef.current;
    if (!container) {
      // Overlay should have mounted the ref before we get here; wait a frame
      // for React to paint and retry. After a few frames give up and create
      // a zero-size offscreen fallback so the hook still completes (covers
      // contexts that don't render the overlay, e.g. hook unit tests).
      if (retryCountRef.current < 3) {
        retryCountRef.current += 1;
        requestAnimationFrame(() => void renderWidget());
        return;
      }
      if (!fallbackContainerRef.current) {
        const el = document.createElement('div');
        el.setAttribute('data-testid', 'hv-widget-fallback');
        Object.assign(el.style, {
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: '10000',
          width: '0',
          height: '0',
          overflow: 'visible',
          pointerEvents: 'none',
        });
        document.body.appendChild(el);
        fallbackContainerRef.current = el;
      }
      container = fallbackContainerRef.current;
    }

    if (widgetIdRef.current) {
      window.turnstile.reset(widgetIdRef.current);
      return;
    }

    widgetIdRef.current = window.turnstile.render(container, {
      sitekey,
      appearance: 'interaction-only',
      size: 'normal',
      callback: (token: string) => {
        void submitToken(token);
      },
      'error-callback': () => {
        if (mountedRef.current) setState('failed');
        flushFailed();
      },
      'expired-callback': () => {
        if (!mountedRef.current) return;
        setState('idle');
        if (widgetIdRef.current && window.turnstile) {
          window.turnstile.reset(widgetIdRef.current);
        }
      },
      // Cloudflare invokes this when an invisible challenge escalates to a
      // visible one. We flip state so the overlay reveals the widget. If
      // this callback name turns out not to exist in the current Turnstile
      // JS API, an iframe-size polling fallback is the next step.
      'before-interactive-callback': () => {
        if (mountedRef.current) setState('challenge');
      },
    } as Parameters<typeof window.turnstile.render>[1]);
  }, [submitToken, flushVerified, flushFailed]);

  useEffect(() => {
    mountedRef.current = true;
    void (async () => {
      try {
        const status = await api.getVerifyStatus();
        if (!mountedRef.current) return;
        if (status.verified) {
          setState('verified');
          flushVerified();
          return;
        }
      } catch {
        // /verify-status failure (network / 5xx) falls through to Turnstile
      }
      try {
        // A reverify() triggered while the probe was in flight may already
        // have rendered the widget — don't reset its in-progress challenge.
        if (!widgetIdRef.current) {
          await renderWidget();
        }
      } catch {
        if (mountedRef.current) setState('failed');
        flushFailed();
      }
    })();
    return () => {
      mountedRef.current = false;
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
      if (fallbackContainerRef.current) {
        fallbackContainerRef.current.remove();
        fallbackContainerRef.current = null;
      }
    };
  }, [flushFailed, flushVerified, renderWidget]);

  const ensureVerified = useCallback((): Promise<void> => {
    if (stateRef.current === 'verified') return Promise.resolve();
    return waitForVerified();
  }, [waitForVerified]);

  const reverify = useCallback((): Promise<void> => {
    if (!mountedRef.current) return Promise.resolve();
    const current = stateRef.current;
    // A challenge is already in flight — resetting would restart it (and
    // delay every gated call on the page). Wait for it to settle instead.
    if (reverifyInFlightRef.current || current === 'loading' || current === 'challenge') {
      return waitForVerified();
    }
    // 'verified' (server rejected a stale/missing cookie), 'idle', or
    // 'failed': re-run the challenge. Register the waiter BEFORE kicking the
    // widget so a synchronous flush can't be missed.
    reverifyInFlightRef.current = true;
    const settled = waitForVerified();
    setState('loading');
    if (widgetIdRef.current && window.turnstile) {
      window.turnstile.reset(widgetIdRef.current);
    } else {
      void renderWidget().catch(() => {
        if (mountedRef.current) setState('failed');
        flushFailed();
      });
    }
    return settled;
  }, [renderWidget, waitForVerified, flushFailed]);

  const retry = useCallback(() => {
    if (widgetIdRef.current && window.turnstile) {
      window.turnstile.remove(widgetIdRef.current);
      widgetIdRef.current = null;
    }
    void renderWidget();
  }, [renderWidget]);

  return { state, ensureVerified, reverify, retry, widgetContainerRef };
}
