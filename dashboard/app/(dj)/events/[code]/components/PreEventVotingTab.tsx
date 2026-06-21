'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { z } from 'zod';
import { apiClient, PendingReviewRow } from '@/lib/api';
import type { SortDirection } from '@/lib/api-types';
import { loadAllPages, type PageFetcher } from '@/lib/load-all-pages';
import {
  PENDING_REVIEW_DEFAULT_DIRECTION,
  PENDING_REVIEW_SORT_FIELDS,
  REVIEW_ORDER,
  type PendingReviewSort,
} from '@/lib/pending-review-sort';
import { sortRequests, type ClientSortField } from '@/lib/request-sort';

interface EventShape {
  code: string;
  name: string;
  collection_opens_at: string | null;
  live_starts_at: string | null;
  submission_cap_per_guest: number;
  collection_phase_override: 'force_collection' | 'force_live' | null;
  phase: 'pre_announce' | 'collection' | 'live' | 'closed';
  tidal_sync_enabled: boolean;
  tidal_collection_playlist_id: string | null;
  tidal_collection_bidirectional: boolean;
}

interface Props {
  event: EventShape;
  tidalConnected: boolean;
  tidalIntegrationEnabled: boolean;
  onEventChange: (next: Partial<EventShape>) => void;
}

type ConfirmAction = 'force_collection' | 'force_live' | 'clear';

type BulkReviewAction = Parameters<typeof apiClient.bulkReview>[1]['action'];

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

const CONFIRM_LABEL: Record<ConfirmAction, string> = {
  force_collection: 'Open collection now',
  force_live: 'Start live now',
  clear: 'Clear phase override',
};

const collectionSchema = z
  .object({
    collection_opens_at: z.string().optional(),
    live_starts_at: z.string().optional(),
    submission_cap_per_guest: z.number().int().min(0).max(100).optional(),
  })
  .refine(
    (v) => {
      if (v.collection_opens_at && v.live_starts_at) {
        return new Date(v.collection_opens_at) < new Date(v.live_starts_at);
      }
      return true;
    },
    { message: 'Collection opens must be before live starts' },
  );

function toDatetimeLocal(iso: string | null): string {
  if (!iso) return '';
  return iso.slice(0, 16);
}

function toIso(local: string): string | null {
  if (!local) return null;
  return new Date(local).toISOString();
}

export default function PreEventVotingTab({
  event,
  tidalConnected,
  tidalIntegrationEnabled,
  onEventChange,
}: Props) {
  // The whole pending-review set is loaded once (chunked to the 2000 cap) and
  // sorted/filtered in memory (issue #489): `allPending` is the loaded set in the
  // server's vote-ranked Review order; `pending` is the in-memory sorted view.
  const [allPending, setAllPending] = useState<PendingReviewRow[]>([]);
  const [pendingTotal, setPendingTotal] = useState(0);
  const [capped, setCapped] = useState(false);
  const [sortField, setSortField] = useState<PendingReviewSort>(REVIEW_ORDER);
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirming, setConfirming] = useState<ConfirmAction | null>(null);
  const [topN, setTopN] = useState(20);
  const [minVotes, setMinVotes] = useState(3);

  const [collectionOpensAt, setCollectionOpensAt] = useState(
    toDatetimeLocal(event.collection_opens_at),
  );
  const [liveStartsAt, setLiveStartsAt] = useState(toDatetimeLocal(event.live_starts_at));
  const [submissionCap, setSubmissionCap] = useState(event.submission_cap_per_guest);
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsSaved, setSettingsSaved] = useState(false);

  const [togglingTidal, setTogglingTidal] = useState(false);
  const [togglingBidirectional, setTogglingBidirectional] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<{ queued: number } | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  // Load the whole pending-review set once (chunked to the 2000 cap) in the
  // server's Review order, then sort in memory (issue #489). A sequence ref drops
  // stale in-flight responses so an older load can't overwrite newer rows.
  const pendingFetchSeqRef = useRef(0);

  const fetchAll = useCallback(async (): Promise<void> => {
    const seq = ++pendingFetchSeqRef.current;
    // Fetch in the stable default Review order (no sort param) so the chunked
    // offset paging stitches deterministically; client-sort happens below.
    const fetcher: PageFetcher<PendingReviewRow> = async ({ limit, offset }) => {
      const resp = await apiClient.getPendingReview(event.code, { limit, offset });
      return { requests: resp.requests, total: resp.total };
    };
    try {
      const res = await loadAllPages(fetcher);
      if (seq !== pendingFetchSeqRef.current) return;
      setAllPending(res.requests);
      setPendingTotal(res.total);
      setCapped(res.capped);
    } catch {
      // Keep the last-good set on failure.
    }
  }, [event.code]);

  // Reload only when the event changes; sort/direction are applied in memory.
  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  /** Re-load the full set (used after bulk actions). */
  const refresh = fetchAll;

  // Client-sorted view: Review order renders as the server returned it; simple
  // fields sort the in-memory set instantly (no re-fetch).
  const pending = useMemo(() => {
    if (sortField === REVIEW_ORDER) return allPending;
    return sortRequests(allPending, sortField as ClientSortField, sortDirection);
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

  async function applyOverride(value: 'force_collection' | 'force_live' | null) {
    const resp = await apiClient.patchCollectionSettings(event.code, {
      collection_phase_override: value,
    });
    onEventChange(resp);
    setConfirming(null);
  }

  async function bulk(action: string, extras: Record<string, unknown> = {}) {
    await apiClient.bulkReview(event.code, {
      action: assertBulkReviewAction(action),
      ...extras,
    });
    setSelected(new Set());
    refresh();
  }

  async function handleSaveSettings(e: React.FormEvent) {
    e.preventDefault();
    setSettingsError(null);
    setSettingsSaved(false);

    const parsed = collectionSchema.safeParse({
      collection_opens_at: collectionOpensAt || undefined,
      live_starts_at: liveStartsAt || undefined,
      submission_cap_per_guest: submissionCap,
    });

    if (!parsed.success) {
      setSettingsError(parsed.error.issues[0].message);
      return;
    }

    setSavingSettings(true);
    try {
      const resp = await apiClient.patchCollectionSettings(event.code, {
        collection_opens_at: toIso(collectionOpensAt),
        live_starts_at: toIso(liveStartsAt),
        submission_cap_per_guest: submissionCap,
      });
      onEventChange(resp);
      setSettingsSaved(true);
      setTimeout(() => setSettingsSaved(false), 3000);
    } catch (err) {
      setSettingsError(err instanceof Error ? err.message : 'Failed to save settings');
    } finally {
      setSavingSettings(false);
    }
  }

  async function handleToggleTidalSync(enabled: boolean) {
    setTogglingTidal(true);
    setSyncError(null);
    try {
      const resp = await apiClient.patchCollectionSettings(event.code, {
        tidal_sync_enabled: enabled,
      });
      onEventChange(resp);
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : 'Failed to update Tidal sync setting');
    } finally {
      setTogglingTidal(false);
    }
  }

  async function handleToggleBidirectional(enabled: boolean) {
    setTogglingBidirectional(true);
    setSyncError(null);
    try {
      const resp = await apiClient.patchCollectionSettings(event.code, {
        tidal_collection_bidirectional: enabled,
      });
      onEventChange(resp);
    } catch (err) {
      setSyncError(
        err instanceof Error ? err.message : 'Failed to update bidirectional sync setting',
      );
    } finally {
      setTogglingBidirectional(false);
    }
  }

  async function handleSyncToTidal() {
    setSyncing(true);
    setSyncResult(null);
    setSyncError(null);
    try {
      const result = await apiClient.syncCollectionToTidal(event.code);
      setSyncResult(result);
      setTimeout(() => setSyncResult(null), 5000);
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : 'Sync failed');
      setTimeout(() => setSyncError(null), 5000);
    } finally {
      setSyncing(false);
    }
  }

  const shareUrl =
    typeof window !== 'undefined'
      ? `${window.location.origin}/collect/${event.code}`
      : `/collect/${event.code}`;

  function toggleRow(id: number, checked: boolean) {
    const next = new Set(selected);
    if (checked) {
      next.add(id);
    } else {
      next.delete(id);
    }
    setSelected(next);
  }

  const showTidalSection = tidalConnected && tidalIntegrationEnabled;

  return (
    <div style={{ padding: '1rem' }}>
      <h2 style={{ marginBottom: '1rem' }}>Pre-Event Voting</h2>

      {!event.collection_opens_at && !event.live_starts_at && (
        <div
          style={{
            padding: '0.875rem 1rem',
            background: 'var(--color-primary-subtle)',
            border: '1px solid var(--color-primary-subtle)',
            borderRadius: 8,
            color: 'var(--color-link)',
            marginBottom: '1.25rem',
            fontSize: '0.9rem',
          }}
        >
          Pre-event voting isn&apos;t enabled yet. Set the dates below to turn it
          on — guests can then visit the share link to suggest and upvote songs
          ahead of the live event.
        </div>
      )}

      <div className="pre-event-stats">
        <div className="pre-event-stat">
          <div className="pre-event-stat-label">Current phase</div>
          <div className="pre-event-stat-value">{event.phase.replace('_', ' ')}</div>
        </div>
        <div className="pre-event-stat">
          <div className="pre-event-stat-label">Pending review</div>
          <div className="pre-event-stat-value">{pendingTotal}</div>
        </div>
        <div className="pre-event-stat">
          <div className="pre-event-stat-label">Pick cap / guest</div>
          <div className="pre-event-stat-value">
            {event.submission_cap_per_guest === 0 ? '∞' : event.submission_cap_per_guest}
          </div>
        </div>
      </div>

      <div className="pre-event-share">
        <code>{shareUrl}</code>
        <button
          type="button"
          className="btn btn-sm"
          style={{ background: 'var(--border)', color: 'var(--text)' }}
          onClick={() => navigator.clipboard.writeText(shareUrl)}
        >
          Copy
        </button>
      </div>

      <div className="card" style={{ marginBottom: '1.25rem' }}>
        <h3 style={{ marginBottom: '0.75rem', fontSize: '1rem' }}>Collection Settings</h3>
        <form onSubmit={handleSaveSettings}>
          <div className="form-group">
            <label htmlFor="collection-opens-at">Collection opens at</label>
            <input
              id="collection-opens-at"
              type="datetime-local"
              className="input"
              value={collectionOpensAt}
              onChange={(e) => setCollectionOpensAt(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label htmlFor="live-starts-at">Live starts at</label>
            <input
              id="live-starts-at"
              type="datetime-local"
              className="input"
              value={liveStartsAt}
              onChange={(e) => setLiveStartsAt(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label htmlFor="submission-cap">Submission cap per guest</label>
            <input
              id="submission-cap"
              type="number"
              min={0}
              max={100}
              className="input collection-fieldset-cap"
              value={submissionCap}
              onChange={(e) => setSubmissionCap(Number(e.target.value))}
            />
            <p className="collection-fieldset-hint">0 = unlimited picks per guest</p>
          </div>
          {settingsError && <p className="collection-fieldset-error">{settingsError}</p>}
          {settingsSaved && (
            <p style={{ color: 'var(--color-success)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              Settings saved.
            </p>
          )}
          <button type="submit" className="btn btn-primary btn-sm" disabled={savingSettings}>
            {savingSettings ? 'Saving…' : 'Save settings'}
          </button>
        </form>
      </div>

      {showTidalSection && (
        <div className="card" style={{ marginBottom: '1.25rem' }}>
          <h3 style={{ marginBottom: '0.75rem', fontSize: '1rem' }}>Tidal Collection Sync</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.875rem' }}>
            Sync guest suggestions to a Tidal playlist so you can listen while you plan your set.
            Playlist name: <strong>{event.code} – {event.name}</strong>
          </p>

          <label className="collection-fieldset-toggle" style={{ marginBottom: '0.875rem' }}>
            <input
              type="checkbox"
              checked={event.tidal_sync_enabled}
              disabled={togglingTidal}
              onChange={(e) => handleToggleTidalSync(e.target.checked)}
            />
            Enable Tidal sync for this collection
          </label>

          {event.tidal_sync_enabled && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ background: '#1db954', color: '#fff' }}
                  disabled={syncing}
                  onClick={handleSyncToTidal}
                >
                  {syncing ? 'Syncing…' : 'Sync collection to Tidal'}
                </button>
                {event.tidal_collection_playlist_id && (
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Pre-event playlist linked ✓
                  </span>
                )}
                {syncResult !== null && (
                  <span style={{ fontSize: '0.875rem', color: 'var(--color-success)' }}>
                    {syncResult.queued === 0
                      ? 'All tracks already synced.'
                      : `Queued ${syncResult.queued} track${syncResult.queued === 1 ? '' : 's'} for sync.`}
                  </span>
                )}
                {syncError && (
                  <span style={{ fontSize: '0.875rem', color: 'var(--color-danger)' }}>{syncError}</span>
                )}
              </div>
              <label className="collection-fieldset-toggle">
                <input
                  type="checkbox"
                  checked={event.tidal_collection_bidirectional}
                  disabled={togglingBidirectional}
                  onChange={(e) => handleToggleBidirectional(e.target.checked)}
                />
                Songs removed from Tidal playlist are auto-rejected
              </label>
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ marginBottom: '1.25rem' }}>
        <h3 style={{ marginBottom: '0.75rem', fontSize: '1rem' }}>Phase controls</h3>
        <div className="pre-event-override-actions">
          <button
            type="button"
            className="btn btn-sm"
            style={{ background: 'var(--border)', color: 'var(--text)' }}
            onClick={() => setConfirming('force_collection')}
          >
            Open collection now
          </button>
          <button
            type="button"
            className="btn btn-sm btn-success"
            onClick={() => setConfirming('force_live')}
          >
            Start live now
          </button>
          <button
            type="button"
            className="btn btn-sm"
            style={{ background: 'var(--border)', color: 'var(--text)' }}
            onClick={() => setConfirming('clear')}
          >
            Clear override
          </button>
        </div>

        {confirming && (
          <div className="pre-event-confirm">
            <span>Confirm: {CONFIRM_LABEL[confirming]}?</span>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => applyOverride(confirming === 'clear' ? null : confirming)}
            >
              Confirm
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        )}
      </div>

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

        <div className="pre-event-review-controls">
          <label>
            Top N:
            <input
              type="number"
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value))}
            />
            <button
              type="button"
              className="btn btn-sm btn-success"
              onClick={() => bulk('accept_top_n', { n: topN })}
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
            />
            <button
              type="button"
              className="btn btn-sm btn-success"
              onClick={() => bulk('accept_threshold', { min_votes: minVotes })}
            >
              Accept threshold
            </button>
          </label>
          <button
            type="button"
            className="btn btn-sm btn-danger"
            onClick={() => bulk('reject_remaining')}
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
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        onClick={() => bulk('reject_ids', { request_ids: [r.id] })}
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
                Showing 2000 of {pendingTotal} requests — sort/filter limited to these.
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
            >
              Accept selected
            </button>
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => bulk('reject_ids', { request_ids: Array.from(selected) })}
            >
              Reject selected
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
