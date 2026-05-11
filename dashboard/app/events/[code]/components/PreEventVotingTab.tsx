'use client';

import { useEffect, useState } from 'react';
import { z } from 'zod';
import { apiClient, PendingReviewRow } from '@/lib/api';

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
  const [pending, setPending] = useState<PendingReviewRow[]>([]);
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
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<{ queued: number } | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  useEffect(() => {
    refresh();

  }, [event.code]);

  async function refresh() {
    const resp = await apiClient.getPendingReview(event.code);
    setPending(resp.requests);
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
            background: 'rgba(59, 130, 246, 0.12)',
            border: '1px solid rgba(59, 130, 246, 0.25)',
            borderRadius: 8,
            color: '#60a5fa',
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
          <div className="pre-event-stat-value">{pending.length}</div>
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
            <p style={{ color: '#4ade80', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
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
                <span style={{ fontSize: '0.875rem', color: '#4ade80' }}>
                  {syncResult.queued === 0
                    ? 'All tracks already synced.'
                    : `Queued ${syncResult.queued} track${syncResult.queued === 1 ? '' : 's'} for sync.`}
                </span>
              )}
              {syncError && (
                <span style={{ fontSize: '0.875rem', color: '#f87171' }}>{syncError}</span>
              )}
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
          Pending review ({pending.length})
        </h3>

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
          >
            Reject remaining
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
