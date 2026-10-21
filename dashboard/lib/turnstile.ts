/**
 * Cloudflare Turnstile loader + site-key cache.
 *
 * Used by the human-verification bootstrap on guest pages (/join, /collect).
 * Loads the Turnstile JS once per page session and caches the site key
 * fetched from /api/auth/settings.
 *
 * Spec: docs/superpowers/specs/2026-05-01-public-page-human-verification-design.md
 */

import { api } from './api';

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: string | HTMLElement,
        options: TurnstileOptions
      ) => string;
      reset: (widgetId?: string) => void;
      remove: (widgetId: string) => void;
      getResponse: (widgetId?: string) => string | undefined;
      ready: (callback: () => void) => void;
    };
  }
}

export interface TurnstileOptions {
  sitekey: string;
  callback?: (token: string) => void;
  'error-callback'?: () => void;
  'expired-callback'?: () => void;
  'timeout-callback'?: () => void;
  appearance?: 'always' | 'execute' | 'interaction-only';
  size?: 'normal' | 'flexible' | 'compact' | 'invisible';
  theme?: 'light' | 'dark' | 'auto';
}

const SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
const SCRIPT_LOAD_TIMEOUT_MS = 15_000;
let scriptLoadPromise: Promise<void> | null = null;
let cachedSiteKey: string | null = null;

export async function getTurnstileSiteKey(): Promise<string> {
  if (cachedSiteKey !== null) return cachedSiteKey;
  const settings = await api.getPublicSettings();
  cachedSiteKey = settings.turnstile_site_key || '';
  return cachedSiteKey;
}

export function loadTurnstileScript(): Promise<void> {
  if (typeof window === 'undefined') return Promise.resolve();
  if (window.turnstile) return Promise.resolve();
  if (scriptLoadPromise) return scriptLoadPromise;

  const existing = document.querySelector<HTMLScriptElement>(`script[src^="${SCRIPT_URL}"]`);
  const script = existing ?? document.createElement('script');
  let resolveLoad!: () => void;
  let rejectLoad!: (error: Error) => void;
  const loadPromise = new Promise<void>((resolve, reject) => {
    resolveLoad = resolve;
    rejectLoad = reject;
  });
  scriptLoadPromise = loadPromise;

  let settled = false;
  const cleanup = () => {
    window.clearTimeout(timeoutId);
    script.removeEventListener('load', handleLoad);
    script.removeEventListener('error', handleError);
  };
  const fail = () => {
    if (settled) return;
    settled = true;
    cleanup();
    script.remove();
    if (scriptLoadPromise === loadPromise) scriptLoadPromise = null;
    rejectLoad(new Error('Turnstile script failed to load'));
  };
  const handleLoad = () => {
    if (!window.turnstile) {
      fail();
      return;
    }
    if (settled) return;
    settled = true;
    cleanup();
    resolveLoad();
  };
  const handleError = () => fail();
  const timeoutId = window.setTimeout(fail, SCRIPT_LOAD_TIMEOUT_MS);

  script.addEventListener('load', handleLoad);
  script.addEventListener('error', handleError);
  if (!existing) {
    script.src = SCRIPT_URL;
    script.async = true;
    script.defer = true;
    document.head.appendChild(script);
  }
  // The script may have completed before this caller attached its listeners.
  if (window.turnstile) handleLoad();

  return loadPromise;
}

export function resetTurnstileCache(): void {
  cachedSiteKey = null;
}
