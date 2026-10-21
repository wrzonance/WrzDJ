'use client';

import { useEffect, useRef } from 'react';

/**
 * Run `load` on mount and then every `intervalMs` while `enabled` is true.
 *
 * `load` returns `true` to keep polling, `false` to stop permanently (e.g. after
 * a terminal 404/410). Stopping cannot be resumed within the same mount; the
 * caller can force a fresh cycle by remounting or changing `enabled` to
 * false-then-true.
 *
 * Per-page concerns (hasLoadedRef error-flash suppression, SSE wiring,
 * per-fetch state updates) stay in the caller — this primitive only owns the
 * interval lifecycle.
 */
export function usePollingLoop(
  enabled: boolean,
  load: () => Promise<boolean>,
  intervalMs: number = 10_000,
): void {
  // Hold the latest `load` reference so the interval callback sees fresh state
  // even when the caller rebuilds `load` on every render (common when load
  // closes over page-level state that changes frequently).
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let inFlight = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const tick = async () => {
      if (stopped || inFlight) return;
      inFlight = true;
      try {
        const shouldContinue = await loadRef.current();
        if (!shouldContinue) {
          stopped = true;
          if (intervalId !== null) {
            clearInterval(intervalId);
            intervalId = null;
          }
        }
      } finally {
        inFlight = false;
      }
    };

    tick();

    intervalId = setInterval(() => {
      if (!stopped) {
        tick();
      }
    }, intervalMs);

    return () => {
      if (intervalId !== null) {
        clearInterval(intervalId);
      }
    };
  }, [enabled, intervalMs]);
}
