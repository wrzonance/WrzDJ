/**
 * Chunked "load the whole bounded set once" loader for the event request lists
 * (issue #489). Pages a {requests, total} fetcher PUBLIC_PAGE_MAX rows at a time
 * up to a 2000-row safety cap, so the browser can sort/filter/count in memory.
 */
import { PUBLIC_PAGE_MAX } from '@/lib/api';

/** Hard ceiling on rows loaded for in-memory sort/filter. */
export const REQUEST_LOAD_CAP = 2000;

export interface PageFetchResult<T> {
  requests: T[];
  total: number;
}

export type PageFetcher<T> = (opts: {
  limit: number;
  offset: number;
  signal?: AbortSignal;
}) => Promise<PageFetchResult<T>>;

export interface LoadAllResult<T> {
  requests: T[];
  total: number;
  capped: boolean;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw signal.reason instanceof Error
      ? signal.reason
      : new DOMException('Aborted', 'AbortError');
  }
}

/**
 * Load up to REQUEST_LOAD_CAP rows in PUBLIC_PAGE_MAX chunks. The first fetch
 * establishes `total`; subsequent fetches continue until the capped target is
 * reached. `capped` is true when the event exceeds the cap (the result then holds
 * exactly REQUEST_LOAD_CAP rows in the fetcher's server order). Honors an
 * AbortSignal between and within chunks.
 */
export async function loadAllPages<T>(
  fetcher: PageFetcher<T>,
  opts?: { signal?: AbortSignal },
): Promise<LoadAllResult<T>> {
  const signal = opts?.signal;
  const acc: T[] = [];
  let total = 0;
  let offset = 0;

  for (;;) {
    throwIfAborted(signal);
    const page = await fetcher({ limit: PUBLIC_PAGE_MAX, offset, signal });
    throwIfAborted(signal);

    total = page.total;
    acc.push(...page.requests);
    offset += page.requests.length;

    // Broken-pagination guard: a chunk that returns nothing can't make progress.
    if (page.requests.length === 0) break;

    const target = Math.min(total, REQUEST_LOAD_CAP);
    if (acc.length >= target) break;
  }

  const capped = total > REQUEST_LOAD_CAP;
  const requests = capped ? acc.slice(0, REQUEST_LOAD_CAP) : acc;
  return { requests, total, capped };
}
