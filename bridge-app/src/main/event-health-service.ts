/**
 * Event health check service.
 *
 * Validates that an event still exists via the public API endpoint.
 * No authentication required — returns appropriate HTTP status codes.
 */

export type EventHealthStatus = 'active' | 'not_found' | 'expired' | 'error';

/**
 * Check whether an event still exists and is active.
 *
 * Uses GET /api/public/events/{code} — the dual-resolver public event endpoint,
 * which accepts EITHER the collection code or the join_code. The bridge is
 * configured with the collection code; the join-code-only
 * /api/public/e/{code}/nowplaying would 404 on it and the health check would
 * misread that as 'not_found' and stop a perfectly live bridge.
 *
 *   200 → active (event exists and is live)
 *   404 → not_found (event was deleted)
 *   410 → expired (event expired or archived)
 *   other → error (network issue, server error — don't act on this)
 */
const HEALTH_CHECK_TIMEOUT_MS = 10_000;

export async function checkEventHealth(
  apiUrl: string,
  eventCode: string,
): Promise<EventHealthStatus> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS);

    try {
      const response = await fetch(
        `${apiUrl}/api/public/events/${encodeURIComponent(eventCode)}`,
        { signal: controller.signal },
      );

      if (response.ok) return 'active';
      if (response.status === 404) return 'not_found';
      if (response.status === 410) return 'expired';

      return 'error';
    } finally {
      clearTimeout(timeoutId);
    }
  } catch {
    return 'error';
  }
}
