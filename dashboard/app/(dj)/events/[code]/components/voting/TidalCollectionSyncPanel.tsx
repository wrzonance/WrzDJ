'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import { PROVIDER_BRAND_COLORS } from '@/lib/provider-brand-colors';
import type { PreEventEventShape } from './PreEventEventShape';

interface Props {
  event: PreEventEventShape;
  onEventChange: (next: Partial<PreEventEventShape>) => void;
}

export default function TidalCollectionSyncPanel({ event, onEventChange }: Props) {
  const [togglingTidal, setTogglingTidal] = useState(false);
  const [togglingBidirectional, setTogglingBidirectional] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<{ queued: number } | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  async function handleToggleTidalSync(enabled: boolean) {
    setTogglingTidal(true);
    setSyncError(null);
    try {
      const resp = await api.patchCollectionSettings(event.code, {
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
      const resp = await api.patchCollectionSettings(event.code, {
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
      const result = await api.syncCollectionToTidal(event.code);
      setSyncResult(result);
      setTimeout(() => setSyncResult(null), 5000);
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : 'Sync failed');
      setTimeout(() => setSyncError(null), 5000);
    } finally {
      setSyncing(false);
    }
  }

  return (
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
          onChange={(event) => handleToggleTidalSync(event.target.checked)}
        />
        Enable Tidal sync for this collection
      </label>

      {syncError && (
        <div role="alert" style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
          {syncError}
        </div>
      )}

      {event.tidal_sync_enabled && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="btn btn-sm"
              style={{ background: PROVIDER_BRAND_COLORS.spotify, color: 'var(--text-on-bright-accent)' }}
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
          </div>
          <label className="collection-fieldset-toggle">
            <input
              type="checkbox"
              checked={event.tidal_collection_bidirectional}
              disabled={togglingBidirectional}
              onChange={(inputEvent) => handleToggleBidirectional(inputEvent.target.checked)}
            />
            Songs removed from Tidal playlist are auto-rejected
          </label>
        </div>
      )}
    </div>
  );
}
