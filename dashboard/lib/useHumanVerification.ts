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

export interface UseHumanVerification {
  state: HumanVerificationState;
  ensureVerified: () => Promise<void>;
  reverify: () => Promise<void>;
  widgetContainerRef: React.RefObject<HTMLDivElement | null>;
}

export function useHumanVerification(): UseHumanVerification {
  const [state, setState] = useState<HumanVerificationState>('idle');
  const widgetContainerRef = useRef<HTMLDivElement | null>(null);
  const fallbackContainerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const verifiedResolversRef = useRef<Array<() => void>>([]);
  const stateRef = useRef(state);
  stateRef.current = state;

  const submitToken = useCallback(async (token: string) => {
    try {
      const result = await api.verifyHuman(token);
      if (result.verified) {
        setState('verified');
        verifiedResolversRef.current.forEach((resolve) => resolve());
        verifiedResolversRef.current = [];
      } else {
        setState('failed');
      }
    } catch {
      setState('failed');
    }
  }, []);

  const renderWidget = useCallback(async () => {
    setState('loading');
    const sitekey = await getTurnstileSiteKey();
    if (!sitekey) {
      // No site key configured (dev / Turnstile-disabled deploy) — treat as verified
      setState('verified');
      verifiedResolversRef.current.forEach((resolve) => resolve());
      verifiedResolversRef.current = [];
      return;
    }
    await loadTurnstileScript();
    if (!window.turnstile) return;

    // Use the page-supplied ref container if it's attached; otherwise create a
    // visible fallback positioned at center-screen. Cloudflare can escalate
    // from invisible to visible challenge on suspicious sessions, so the
    // fallback container MUST be reachable to the user — a display:none
    // fallback would trap visible-challenge escalations and lock the guest
    // out of any page that hasn't rendered its widget container yet (e.g.
    // collect pages where the page-level container sits behind a gate
    // early-return that hasn't mounted yet).
    let container = widgetContainerRef.current;
    let fallbackOwned = false;
    if (!container) {
      container = document.createElement('div');
      container.setAttribute('data-testid', 'human-verify-fallback');
      // Zero-size, pointer-events:none container. Cloudflare's injected
      // iframe sizes itself for invisible vs visible challenge mode and
      // overflows the container naturally; the wrapper just provides a
      // stable, centered anchor point in the DOM. Pointer-events:none
      // ensures the container doesn't intercept clicks on underlying gate
      // UI when no challenge is being shown.
      Object.assign(container.style, {
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
      // Re-enable pointer events on the injected iframe so the user can
      // interact with a visible challenge widget when Cloudflare escalates.
      const styleEl = document.createElement('style');
      styleEl.textContent = `
        [data-testid="human-verify-fallback"] iframe { pointer-events: auto; }
      `;
      document.head.appendChild(styleEl);
      document.body.appendChild(container);
      fallbackOwned = true;
    }
    // Track for cleanup so we can remove the fallback on unmount
    if (fallbackOwned) {
      fallbackContainerRef.current = container;
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
      'error-callback': () => setState('failed'),
      'expired-callback': () => {
        setState('idle');
        if (widgetIdRef.current && window.turnstile) {
          window.turnstile.reset(widgetIdRef.current);
        }
      },
    });
  }, [submitToken]);

  useEffect(() => {
    void renderWidget();
    return () => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
      if (fallbackContainerRef.current) {
        fallbackContainerRef.current.remove();
        fallbackContainerRef.current = null;
      }
    };
  }, []);

  const ensureVerified = useCallback((): Promise<void> => {
    if (stateRef.current === 'verified') return Promise.resolve();
    return new Promise((resolve) => {
      verifiedResolversRef.current.push(resolve);
    });
  }, []);

  const reverify = useCallback(async () => {
    if (widgetIdRef.current && window.turnstile) {
      window.turnstile.reset(widgetIdRef.current);
    }
    setState('loading');
    await renderWidget();
  }, [renderWidget]);

  return { state, ensureVerified, reverify, widgetContainerRef };
}
