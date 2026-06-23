/**
 * Shared HTTP retry/backoff/timeout primitives for the WrzDJ bridge artifacts.
 *
 * Consumed by both the headless bridge (`bridge/src/bridge.ts`, imported as
 * `./http-retry.js`) and the Electron bridge app
 * (`bridge-app/src/main/bridge-runner.ts`, imported via the `@bridge/*` alias as
 * `@bridge/http-retry.js` — the same pattern `bridge-runner.ts` already uses for
 * `@bridge/circuit-breaker.js`).
 *
 * This module owns ONLY the genuinely identical primitives — the retry/backoff
 * constants, the `AbortController`-based fetch timeout, and the exponential
 * backoff math + sleep. The retry loops themselves stay in each artifact because
 * they diverge legitimately: the bridge app records `backendReachable`/status
 * transitions and stops the bridge on a 401 (token expiry), neither of which the
 * headless bridge does. That divergence must NOT be folded in here.
 */

/** Number of POST retries after the initial attempt. */
export const MAX_RETRIES = 3;
/** Base backoff for POST retries (doubles per attempt). */
export const INITIAL_BACKOFF_MS = 2000;
/** AbortController timeout applied to every fetch. */
export const FETCH_TIMEOUT_MS = 10_000;
/** Number of DELETE retries after the initial attempt. */
export const DELETE_MAX_RETRIES = 2;
/** Base backoff for DELETE retries (doubles per attempt). */
export const DELETE_BACKOFF_MS = 1000;

/**
 * Make a fetch request with an AbortController timeout.
 *
 * The timer is always cleared in a `finally` so it never leaks, regardless of
 * whether the fetch resolves, rejects, or is aborted.
 */
export async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeoutMs: number = FETCH_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Exponential backoff for a given retry attempt: `baseMs * 2 ** attempt`.
 *
 * @param baseMs   the base backoff in milliseconds
 * @param attempt  zero-based attempt index (0 → baseMs, 1 → 2·baseMs, …)
 */
export function computeBackoff(baseMs: number, attempt: number): number {
  return baseMs * Math.pow(2, attempt);
}

/** Resolve after `ms` milliseconds (respects fake timers in tests). */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
