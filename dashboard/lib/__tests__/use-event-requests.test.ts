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
});
