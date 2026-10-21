export const POLL_INTERVAL_MS = 10000;
export const BACKOFF_INTERVAL_MS = 60000;
/* Request list is a growing window: "Load more" grows displayLimit and every
   poll/SSE refresh re-fetches [0, displayLimit) so live vote/status updates
   stay correct without client-side dedup. */
export const PAGE_SIZE = 100;

export const ACCENT = '#00f0ff';
export const ACCENT2 = '#ff2bd6';
