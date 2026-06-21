import { describe, it, expect, vi } from 'vitest';
import { loadAllPages, REQUEST_LOAD_CAP, type PageFetcher } from '../load-all-pages';

// Build a fetcher over a fixed-size virtual dataset using PUBLIC_PAGE_MAX=500.
function makeFetcher(total: number): PageFetcher<{ id: number }> {
  return vi.fn(async ({ limit, offset }) => ({
    total,
    requests: Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, i) => ({
      id: offset + i,
    })),
  }));
}

describe('loadAllPages', () => {
  it('returns a single short page without extra fetches', async () => {
    const fetcher = makeFetcher(30);
    const res = await loadAllPages(fetcher);
    expect(res.requests).toHaveLength(30);
    expect(res.total).toBe(30);
    expect(res.capped).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('stitches multiple 500-row pages up to total', async () => {
    const fetcher = makeFetcher(1200);
    const res = await loadAllPages(fetcher);
    expect(res.requests).toHaveLength(1200);
    expect(res.requests.map((r) => r.id)).toEqual(Array.from({ length: 1200 }, (_, i) => i));
    expect(res.capped).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(3); // 500 + 500 + 200
  });

  it('caps at REQUEST_LOAD_CAP and flags capped', async () => {
    const fetcher = makeFetcher(5000);
    const res = await loadAllPages(fetcher);
    expect(res.requests).toHaveLength(REQUEST_LOAD_CAP);
    expect(res.total).toBe(5000);
    expect(res.capped).toBe(true);
  });

  it('stops on an unexpectedly empty chunk (broken pagination guard)', async () => {
    let call = 0;
    const fetcher: PageFetcher<{ id: number }> = vi.fn(async ({ offset }) => {
      call += 1;
      // Claims 5000 total but returns an empty second page.
      if (call === 1) return { total: 5000, requests: Array.from({ length: 500 }, (_, i) => ({ id: offset + i })) };
      return { total: 5000, requests: [] };
    });
    const res = await loadAllPages(fetcher);
    expect(res.requests).toHaveLength(500);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('aborts when the signal fires', async () => {
    const controller = new AbortController();
    const fetcher: PageFetcher<{ id: number }> = vi.fn(async () => {
      controller.abort();
      return { total: 5000, requests: Array.from({ length: 500 }, (_, i) => ({ id: i })) };
    });
    await expect(loadAllPages(fetcher, { signal: controller.signal })).rejects.toThrow();
  });

  it('surfaces server status_counts from the fetcher (issue #521)', async () => {
    const counts = { all: 5000, new: 4200, accepted: 600, playing: 0, played: 150, rejected: 50 };
    const fetcher: PageFetcher<{ id: number }> = vi.fn(async ({ limit, offset }) => ({
      total: 5000,
      statusCounts: counts,
      requests: Array.from({ length: Math.max(0, Math.min(limit, 5000 - offset)) }, (_, i) => ({
        id: offset + i,
      })),
    }));
    const res = await loadAllPages(fetcher);
    expect(res.capped).toBe(true);
    expect(res.requests).toHaveLength(REQUEST_LOAD_CAP); // client view is truncated
    expect(res.statusCounts).toEqual(counts); // ...but counts are authoritative
  });

  it('leaves statusCounts undefined when the fetcher omits it', async () => {
    const res = await loadAllPages(makeFetcher(30));
    expect(res.statusCounts).toBeUndefined();
  });
});
