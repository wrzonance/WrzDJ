'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, SongRequest } from '@/lib/api';
import type { RequestSort, SortDirection } from '@/lib/api-types';
import type { StatusFilter } from '@/app/(dj)/events/[code]/components/types';
import { loadAllPages, type PageFetcher } from './load-all-pages';
import {
  computeStatusCounts,
  filterByStatus,
  sortRequests,
  type ClientSortField,
} from './request-sort';

/** Collapse a burst of SSE-driven refetches into one network load. */
const REFETCH_DEBOUNCE_MS = 500;

export interface UseEventRequestsResult {
  /** Full loaded set (already capped) in the fetcher's order — source of truth. */
  allRequests: SongRequest[];
  /** Derived view: filtered by status then client-sorted (or server-ordered for best_match). */
  visibleRequests: SongRequest[];
  /** In-memory total when not capped; the honest server total when capped. */
  total: number;
  /** True when the event exceeds the 2000-row in-memory cap. */
  capped: boolean;
  statusCounts: Record<StatusFilter, number>;
  loading: boolean;
  error: string | null;
  /** Replace the full set (optimistic patches re-derive the visible view via memo). */
  setAllRequests: React.Dispatch<React.SetStateAction<SongRequest[]>>;
  /** Force an immediate (coalescing-cancelling) refetch — used after mutations. */
  refetch: () => void;
  /** Schedule a debounced refetch — used by SSE so a burst collapses to one load. */
  scheduleRefetch: () => void;
}

/**
 * Main-queue data orchestration (issue #489). Loads the whole bounded event
 * request set once (chunked to the 2000 cap), then sorts/filters/counts in
 * memory so toggles are instant. `best_match` is fetched in server order and
 * never client re-sorted; the 7 simple fields are sorted in memory. Live updates
 * arrive as a coalesced refetch; an AbortController drops superseded loads.
 */
export function useEventRequests(params: {
  code: string;
  enabled: boolean;
  sortField: RequestSort;
  sortDirection: SortDirection;
  statusFilter: StatusFilter;
}): UseEventRequestsResult {
  const { code, enabled, sortField, sortDirection, statusFilter } = params;

  const [allRequests, setAllRequests] = useState<SongRequest[]>([]);
  const [serverTotal, setServerTotal] = useState(0);
  const [capped, setCapped] = useState(false);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The fetcher reads the live sort field via a ref so a refetch always uses the
  // current order (best_match → server order; simple fields → server default).
  const sortFieldRef = useRef(sortField);
  sortFieldRef.current = sortField;

  const runLoad = useCallback(async () => {
    if (!enabled) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);

    const isBestMatch = sortFieldRef.current === 'best_match';
    const fetcher: PageFetcher<SongRequest> = async ({ limit, offset }) => {
      // Load the full event (no status filter) so counts are correct across tabs.
      // Simple fields fetch the stable server default order, then sort in memory.
      const resp = await api.getRequests(code, {
        sort: isBestMatch ? 'best_match' : 'date_requested',
        direction: 'desc',
        limit,
        offset,
      });
      return { requests: resp.requests, total: resp.total };
    };

    try {
      const res = await loadAllPages(fetcher, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setAllRequests(res.requests);
      setServerTotal(res.total);
      setCapped(res.capped);
      setError(null);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : 'Failed to load requests');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [code, enabled]);

  const refetch = useCallback(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    void runLoad();
  }, [runLoad]);

  const scheduleRefetch = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      void runLoad();
    }, REFETCH_DEBOUNCE_MS);
  }, [runLoad]);

  // Refetch on code/enabled change, and when toggling between best_match (server
  // order) and a simple field (client order). Simple→simple, direction-only, and
  // status changes are handled purely in memory by the memos below — no network.
  const needsServerOrder = sortField === 'best_match';
  useEffect(() => {
    void runLoad();
    return () => {
      abortRef.current?.abort();
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };
  }, [runLoad, needsServerOrder]);

  const visibleRequests = useMemo(() => {
    const filtered = filterByStatus(allRequests, statusFilter);
    if (sortField === 'best_match') return filtered; // render server order as-is
    return sortRequests(filtered, sortField as ClientSortField, sortDirection);
  }, [allRequests, statusFilter, sortField, sortDirection]);

  const statusCounts = useMemo(() => computeStatusCounts(allRequests), [allRequests]);
  const total = capped ? serverTotal : allRequests.length;

  return {
    allRequests,
    visibleRequests,
    total,
    capped,
    statusCounts,
    loading,
    error,
    setAllRequests,
    refetch,
    scheduleRefetch,
  };
}
