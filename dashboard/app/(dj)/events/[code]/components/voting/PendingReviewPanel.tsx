'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, type PendingReviewRow } from '@/lib/api';
import type { SortDirection } from '@/lib/api/types';
import { loadAllPages, REQUEST_LOAD_CAP, type PageFetcher } from '@/lib/load-all-pages';
import {
  PENDING_REVIEW_DEFAULT_DIRECTION,
  PENDING_REVIEW_SORT_FIELDS,
  REVIEW_ORDER,
  type PendingReviewSort,
} from '@/lib/requests/pending-review-sort';
import { isClientSortField, sortRequests } from '@/lib/requests/request-sort';

type BulkReviewAction = Parameters<typeof api.bulkReview>[1]['action'];
type PendingFetchResult = 'loaded' | 'stale' | 'failed';

const BULK_REVIEW_ACTIONS: readonly BulkReviewAction[] = [
  'accept_top_n',
  'accept_threshold',
  'accept_ids',
  'reject_ids',
  'reject_remaining',
];

function assertBulkReviewAction(action: string): BulkReviewAction {
  if (!(BULK_REVIEW_ACTIONS as readonly string[]).includes(action)) {
    throw new Error(`Invalid bulk review action: "${action}"`);
  }
  return action as BulkReviewAction;
}

interface PendingReviewPanelProps {
  eventCode: string;
  onPendingTotalChange: (total: number) => void;
}

export default function PendingReviewPanel({
  eventCode,
  onPendingTotalChange,
}: PendingReviewPanelProps) {
  // The whole pending-review set is loaded once (chunked to the 2000 cap) and
  // sorted/filtered in memory (issue #489): `allPending` is the loaded set in the
  // server's vote-ranked Review order; `pending` is the in-memory sorted view.
  const [allPending, setAllPending] = useState<PendingReviewRow[]>([]);
  const [pendingTotal, setPendingTotal] = useState(0);
  const [capped, setCapped] = useState(false);
  const [sortField, setSortField] = useState<PendingReviewSort>(REVIEW_ORDER);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [topN, setTopN] = useState(20);
  const [minVotes, setMinVotes] = useState(3);
  const [bulkPending, setBulkPending] = useState(false);
  const [refreshPending, setRefreshPending] = useState(false);
  const [bulkError, setBulkError] = useState('');
  const [refreshError, setRefreshError] = useState(false);

  // Load the whole pending-review set once (chunked to the 2000 cap) in the
  // server's Review order, then sort in memory (issue #489). A sequence ref drops
  // stale in-flight responses so an older load can't overwrite newer rows.
  const pendingFetchSeqRef = useRef(0);

  const fetchAll = useCallback(async (): Promise<PendingFetchResult> => {
    const seq = ++pendingFetchSeqRef.current;
    // Fetch in the stable default Review order (no sort param) so the chunked
    // offset paging stitches deterministically; client-sort happens below.
    const fetcher: PageFetcher<PendingReviewRow> = async ({ limit, offset }) => {
      const resp = await api.getPendingReview(eventCode, { limit, offset });
      return { requests: resp.requests, total: resp.total };
    };
    try {
      const res = await loadAllPages(fetcher);
      if (seq !== pendingFetchSeqRef.current) return 'stale';
      setAllPending(res.requests);
      setPendingTotal(res.total);
      onPendingTotalChange(res.total);
      setCapped(res.capped);
      return 'loaded';
    } catch {
      // Keep the last-good set on failure.
      return seq === pendingFetchSeqRef.current ? 'failed' : 'stale';
    }
  }, [eventCode, onPendingTotalChange]);

  // Reload only when the event changes; sort/direction are applied in memory.
  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  async function retryRefresh() {
    if (refreshPending) return;
    setRefreshPending(true);
    const result = await fetchAll();
    if (result === 'loaded') setRefreshError(false);
    if (result === 'failed') setRefreshError(true);
    setRefreshPending(false);
  }

  // Client-sorted view: Review order renders as the server returned it; simple
  // fields sort the in-memory set instantly (no re-fetch).
  const pending = useMemo(() => {
    if (sortField === REVIEW_ORDER || !isClientSortField(sortField)) return allPending;
    return sortRequests(allPending, sortField, sortDirection);
  }, [allPending, sortField, sortDirection]);

  function handleSortFieldChange(next: PendingReviewSort) {
    setSortField(next);
    // Snap direction to the field's natural default; Review order has none.
    if (next !== REVIEW_ORDER) {
      setSortDirection(PENDING_REVIEW_DEFAULT_DIRECTION[next]);
    }
  }

  function handleSortDirectionToggle() {
    setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
  }

  async function bulk(action: string, extras: Record<string, unknown> = {}) {
    if (bulkPending) return;
    let typedAction: BulkReviewAction;
    try {
      typedAction = assertBulkReviewAction(action);
    } catch {
      setBulkError('The review action could not be completed. Please try again.');
      return;
    }

    setBulkPending(true);
    setBulkError('');
    setRefreshError(false);
    try {
      await api.bulkReview(eventCode, { action: typedAction, ...extras });
    } catch {
      setBulkError('The review action failed. Your selection and settings were kept so you can retry.');
      setBulkPending(false);
      return;
    }

    setSelected(new Set());
    const refreshResult = await fetchAll();
    if (refreshResult === 'failed') setRefreshError(true);
    setBulkPending(false);
  }

  function toggleRow(id: number, checked: boolean) {
    const next = new Set(selected);
    if (checked) {
      next.add(id);
    } else {
      next.delete(id);
    }
    setSelected(next);
  }
  return (
    <div className="card">
      <h3 style={{ marginBottom: '0.75rem', fontSize: '1rem' }}>
        Pending review ({pendingTotal})
      </h3>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.375rem',
          marginBottom: '0.75rem',
        }}
      >
        <label
          htmlFor="pending-sort-field"
          style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}
        >
          Sort
        </label>
        <select
          id="pending-sort-field"
          className="input"
          aria-label="Sort pending review by"
          value={sortField}
          onChange={(e) => handleSortFieldChange(e.target.value as PendingReviewSort)}
          style={{ width: 'auto', padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
        >
          {PENDING_REVIEW_SORT_FIELDS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
        {sortField !== REVIEW_ORDER && (
          <button
            type="button"
            className="btn btn-sm"
            style={{ background: 'var(--surface-raised)', fontSize: '0.75rem', minWidth: '2rem' }}
            onClick={handleSortDirectionToggle}
            aria-label={`Sort direction: ${sortDirection === 'asc' ? 'ascending' : 'descending'}`}
            title={sortDirection === 'asc' ? 'Ascending' : 'Descending'}
          >
            {sortDirection === 'asc' ? '↑' : '↓'}
          </button>
        )}
      </div>

      {bulkPending && (
        <p role="status" style={{ color: 'var(--text-secondary)' }}>
          Updating pending requests…
        </p>
      )}
      {bulkError && (
        <div role="alert" style={{ color: 'var(--color-danger)' }}>
          {bulkError}
        </div>
      )}
      {refreshError && (
        <div role="alert" style={{ color: 'var(--color-danger)' }}>
          <p>The review action completed, but the pending list could not refresh.</p>
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={() => void retryRefresh()}
            disabled={refreshPending || bulkPending}
          >
            {refreshPending ? 'Refreshing…' : 'Retry list refresh'}
          </button>
        </div>
      )}

      <div className="pre-event-review-controls">
        <label>
          Top N:
          <input
            type="number"
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            disabled={bulkPending}
          />
          <button
            type="button"
            className="btn btn-sm btn-success"
            onClick={() => bulk('accept_top_n', { n: topN })}
            disabled={bulkPending}
          >
            Accept top N
          </button>
        </label>
        <label>
          ≥ votes:
          <input
            type="number"
            value={minVotes}
            onChange={(e) => setMinVotes(Number(e.target.value))}
            disabled={bulkPending}
          />
          <button
            type="button"
            className="btn btn-sm btn-success"
            onClick={() => bulk('accept_threshold', { min_votes: minVotes })}
            disabled={bulkPending}
          >
            Accept threshold
          </button>
        </label>
        <button
          type="button"
          className="btn btn-sm btn-danger"
          onClick={() => bulk('reject_remaining')}
          disabled={bulkPending}
          title="Rejects every still-pending request server-side — not just the rows loaded below."
        >
          Reject all remaining
        </button>
      </div>

      {pending.length === 0 ? (
        <p className="pre-event-review-empty">No pending requests — all caught up!</p>
      ) : (
        <table className="pre-event-review-table">
          <thead>
            <tr>
              <th></th>
              <th>▲</th>
              <th>Song</th>
              <th>Artist</th>
              <th>Submitted by</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pending.map((r) => (
              <tr key={r.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(r.id)}
                    onChange={(e) => toggleRow(r.id, e.target.checked)}
                    disabled={bulkPending}
                  />
                </td>
                <td>{r.vote_count}</td>
                <td>{r.song_title}</td>
                <td>{r.artist}</td>
                <td>{r.nickname ?? '—'}</td>
                <td>
                  <div className="pre-event-review-actions">
                    <button
                      type="button"
                      className="btn btn-sm btn-success"
                      onClick={() => bulk('accept_ids', { request_ids: [r.id] })}
                      disabled={bulkPending}
                    >
                      Accept
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-danger"
                      onClick={() => bulk('reject_ids', { request_ids: [r.id] })}
                      disabled={bulkPending}
                    >
                      Reject
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {pending.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '0.5rem',
            marginTop: '0.75rem',
          }}
        >
          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            Showing {pending.length} of {pendingTotal}
          </span>
          {capped && (
            <span
              role="status"
              style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}
            >
              Showing {REQUEST_LOAD_CAP} of {pendingTotal} requests — sort/filter limited to these.
            </span>
          )}
        </div>
      )}

      {selected.size > 0 && (
        <div className="pre-event-bulk-selection">
          <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            {selected.size} selected
          </span>
          <button
            type="button"
            className="btn btn-sm btn-success"
            onClick={() => bulk('accept_ids', { request_ids: Array.from(selected) })}
            disabled={bulkPending}
          >
            Accept selected
          </button>
          <button
            type="button"
            className="btn btn-sm btn-danger"
            onClick={() => bulk('reject_ids', { request_ids: Array.from(selected) })}
            disabled={bulkPending}
          >
            Reject selected
          </button>
        </div>
      )}
    </div>
  );
}
