import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useEventRequests } from '../use-event-requests';
import { api } from '@/lib/api';
import type { RequestListResponse } from '@/lib/api-types';
import type { StatusFilter } from '@/app/(dj)/events/[code]/components/types';

function mockList(ids: number[], total = ids.length): RequestListResponse {
  return {
    requests: ids.map((id) => ({
      id,
      created_at: '2026-01-01T00:00:00Z',
      accepted_at: null,
      vote_count: id,
      bpm: null,
      musical_key: null,
      song_title: `s${id}`,
      artist: `a${id}`,
      status: 'new',
      event_id: 1,
      genre: null,
      is_duplicate: false,
      nickname: null,
      note: null,
      priority_score: null,
      raw_search_query: null,
      source: 'manual',
      source_url: null,
      artwork_url: null,
      sync_results_json: null,
      updated_at: '2026-01-01T00:00:00Z',
    })),
    total,
    limit: 500,
    offset: 0,
    sort: 'date_requested',
    direction: 'desc',
    status_counts: { all: total, new: total, accepted: 0, playing: 0, played: 0, rejected: 0 },
  };
}

let getRequestsSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.useFakeTimers();
  getRequestsSpy = vi.spyOn(api, 'getRequests').mockResolvedValue(mockList([3, 2, 1]));
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('useEventRequests', () => {
  it('loads the full set and sorts client-side for a simple field', async () => {
    const { result } = renderHook(() =>
      useEventRequests({
        code: 'EVT',
        enabled: true,
        sortField: 'upvotes',
        sortDirection: 'desc',
        statusFilter: 'all',
      }),
    );
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(result.current.allRequests).toHaveLength(3);
    expect(result.current.visibleRequests.map((r) => r.id)).toEqual([3, 2, 1]);
    expect(result.current.statusCounts.all).toBe(3);
    expect(result.current.total).toBe(3);
    expect(result.current.capped).toBe(false);
  });

  it('filters by status purely in memory (no extra fetch)', async () => {
    const mixed = mockList([1, 2]);
    mixed.requests[0].status = 'new';
    mixed.requests[1].status = 'accepted';
    getRequestsSpy.mockResolvedValue(mixed);
    const { result, rerender } = renderHook(
      (props: { statusFilter: StatusFilter }) =>
        useEventRequests({
          code: 'EVT',
          enabled: true,
          sortField: 'date_requested',
          sortDirection: 'desc',
          statusFilter: props.statusFilter,
        }),
      { initialProps: { statusFilter: 'all' satisfies StatusFilter } },
    );
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(result.current.allRequests).toHaveLength(2);
    getRequestsSpy.mockClear();
    rerender({ statusFilter: 'accepted' });
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(result.current.visibleRequests.map((r) => r.id)).toEqual([2]);
    expect(getRequestsSpy).not.toHaveBeenCalled(); // memo-only, no refetch
  });

  it('coalesces a burst of scheduleRefetch into ONE load', async () => {
    const { result } = renderHook(() =>
      useEventRequests({
        code: 'EVT',
        enabled: true,
        sortField: 'date_requested',
        sortDirection: 'desc',
        statusFilter: 'all',
      }),
    );
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    getRequestsSpy.mockClear();
    act(() => {
      result.current.scheduleRefetch();
      result.current.scheduleRefetch();
      result.current.scheduleRefetch();
    });
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(getRequestsSpy).toHaveBeenCalledTimes(1);
  });

  it('does not client re-sort best_match (renders server order)', async () => {
    getRequestsSpy.mockResolvedValue(mockList([1, 3, 2])); // server order
    const { result } = renderHook(() =>
      useEventRequests({
        code: 'EVT',
        enabled: true,
        sortField: 'best_match',
        sortDirection: 'desc',
        statusFilter: 'all',
      }),
    );
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(result.current.allRequests).toHaveLength(3);
    expect(result.current.visibleRequests.map((r) => r.id)).toEqual([1, 3, 2]);
  });

  it('does not fetch when disabled', async () => {
    renderHook(() =>
      useEventRequests({
        code: 'EVT',
        enabled: false,
        sortField: 'date_requested',
        sortDirection: 'desc',
        statusFilter: 'all',
      }),
    );
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(getRequestsSpy).not.toHaveBeenCalled();
  });

  it('clears loading when enabled flips false mid-flight (CodeRabbit #520)', async () => {
    const { result, rerender } = renderHook(
      (props: { enabled: boolean }) =>
        useEventRequests({
          code: 'EVT',
          enabled: props.enabled,
          sortField: 'date_requested',
          sortDirection: 'desc',
          statusFilter: 'all',
        }),
      { initialProps: { enabled: true } },
    );
    // Disable before the in-flight load resolves; the disabled early-return must
    // still clear the loading flag rather than leave it stuck true.
    rerender({ enabled: false });
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(result.current.loading).toBe(false);
  });

  it('uses server status_counts when the event is capped (issue #521)', async () => {
    // 5000-row event: the client can hold only the 2000-row cap, so counts derived
    // from the in-memory set would undercount. The hook must surface the backend's
    // authoritative per-status counts instead.
    const serverCounts = { all: 5000, new: 4200, accepted: 600, playing: 0, played: 150, rejected: 50 };
    getRequestsSpy.mockImplementation(
      async (_code: string, options?: { limit?: number; offset?: number }) => {
        const offset = options?.offset ?? 0;
        const limit = options?.limit ?? 500;
        const remaining = Math.max(0, 5000 - offset);
        const ids = Array.from({ length: Math.min(limit, remaining) }, (_, i) => offset + i);
        const resp = mockList(ids, 5000);
        resp.status_counts = serverCounts;
        return resp;
      },
    );
    const { result } = renderHook(() =>
      useEventRequests({
        code: 'EVT',
        enabled: true,
        sortField: 'date_requested',
        sortDirection: 'desc',
        statusFilter: 'all',
      }),
    );
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(result.current.capped).toBe(true);
    expect(result.current.allRequests).toHaveLength(2000); // client view truncated
    expect(result.current.total).toBe(5000);
    // Authoritative counts, not the capped-set length (which would be all:2000/new:2000).
    expect(result.current.statusCounts.all).toBe(5000);
    expect(result.current.statusCounts.new).toBe(4200);
    expect(result.current.statusCounts.accepted).toBe(600);
  });

  it('keeps live client-derived counts on the non-capped path (issue #521)', async () => {
    // Non-capped: counts must update LIVE on optimistic in-memory patches (a DJ
    // accepting a request) without waiting for a refetch — so this path stays
    // client-derived rather than frozen at the last server snapshot.
    const { result } = renderHook(() =>
      useEventRequests({
        code: 'EVT',
        enabled: true,
        sortField: 'date_requested',
        sortDirection: 'desc',
        statusFilter: 'all',
      }),
    );
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(result.current.statusCounts.new).toBe(3);
    expect(result.current.statusCounts.accepted).toBe(0);
    act(() => {
      result.current.setAllRequests((prev) =>
        prev.map((r, i) => (i === 0 ? { ...r, status: 'accepted' } : r)),
      );
    });
    expect(result.current.statusCounts.new).toBe(2);
    expect(result.current.statusCounts.accepted).toBe(1);
  });
});
