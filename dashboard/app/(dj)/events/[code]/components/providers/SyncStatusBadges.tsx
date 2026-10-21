'use client';

import { useMemo } from 'react';
import type { SongRequest, SyncResultEntry } from '@/lib/api/types';
import { parseSyncResults } from '@/lib/event-sync';
import { safeExternalUrl } from '@/lib/safe-url';
import { PROVIDER_BRAND_COLORS } from '@/lib/provider-brand-colors';

interface SyncStatusBadgesProps {
  request: SongRequest;
  connectedServices: string[];
  syncingRequest: number | null;
  onSyncToTidal: (requestId: number) => void;
  onOpenTidalPicker: (requestId: number) => void;
  onScrollToSyncReport?: (requestId: number) => void;
}


export function SyncStatusBadges({
  request,
  connectedServices,
  syncingRequest,
  onSyncToTidal,
  onOpenTidalPicker,
  onScrollToSyncReport,
}: SyncStatusBadgesProps) {
  const syncResults = useMemo(() => parseSyncResults(request.sync_results_json), [request.sync_results_json]);

  if (request.status !== 'accepted' || connectedServices.length === 0) {
    return null;
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
      {connectedServices.includes('tidal') && (
        <TidalBadge
          request={request}
          syncResult={syncResults.find(r => r.service === 'tidal')}
          syncing={syncingRequest === request.id}
          onSync={() => onSyncToTidal(request.id)}
          onLink={() => onOpenTidalPicker(request.id)}
        />
      )}
      {connectedServices.includes('beatport') && (
        <BeatportBadge
          syncResult={syncResults.find(r => r.service === 'beatport')}
          onNotFound={() => onScrollToSyncReport?.(request.id)}
        />
      )}
    </div>
  );
}

function TidalBadge({
  request: _request,
  syncResult,
  syncing,
  onSync,
  onLink,
}: {
  request: SongRequest;
  syncResult: SyncResultEntry | undefined;
  syncing: boolean;
  onSync: () => void;
  onLink: () => void;
}) {
  const status = syncResult?.status ?? null;

  if (status === 'added') {
    const url = syncResult?.url;
    if (url) {
      return (
        <a
          href={safeExternalUrl(url) ?? '#'}
          target="_blank"
          rel="noopener noreferrer"
          title="Synced to Tidal - click to view"
          style={{ color: 'var(--color-success)', fontSize: '1rem', fontWeight: 600, textDecoration: 'none', cursor: 'pointer' }}
        >
          T
        </a>
      );
    }
    return (
      <span title="Synced to Tidal" style={{ color: 'var(--color-success)', fontSize: '1rem', cursor: 'default', fontWeight: 600 }}>
        T
      </span>
    );
  }

  if (status === 'not_found') {
    return (
      <button
        className="btn btn-sm"
        style={{ background: 'var(--color-warning)', color: 'white', padding: '0.125rem 0.375rem', fontSize: '0.7rem', lineHeight: 1.2 }}
        onClick={onLink}
        title="Missing from Tidal - click to link manually"
      >
        T?
      </button>
    );
  }

  if (status === 'error') {
    return (
      <button
        className="btn btn-sm"
        style={{ background: 'var(--color-danger)', color: 'white', padding: '0.125rem 0.375rem', fontSize: '0.7rem', lineHeight: 1.2 }}
        onClick={onSync}
        disabled={syncing}
        title="Sync failed - click to retry"
      >
        {syncing ? '...' : 'T!'}
      </button>
    );
  }

  // No status yet — show sync button
  return (
    <button
      className="btn btn-sm"
      style={{ background: PROVIDER_BRAND_COLORS.tidal, padding: '0.125rem 0.375rem', fontSize: '0.7rem', lineHeight: 1.2 }}
      onClick={onSync}
      disabled={syncing}
      title="Sync to Tidal"
    >
      {syncing ? '...' : 'T'}
    </button>
  );
}

function BeatportBadge({
  syncResult,
  onNotFound,
}: {
  syncResult: SyncResultEntry | undefined;
  onNotFound: () => void;
}) {
  const status = syncResult?.status;

  if (status === 'matched' || status === 'added') {
    const url = syncResult?.url;
    if (url) {
      return (
        <a
          href={safeExternalUrl(url) ?? '#'}
          target="_blank"
          rel="noopener noreferrer"
          title="Available on Beatport - click to view"
          style={{ color: PROVIDER_BRAND_COLORS.beatport, fontSize: '1rem', fontWeight: 600, textDecoration: 'none', cursor: 'pointer' }}
        >
          B
        </a>
      );
    }
    return (
      <span title="Found on Beatport" style={{ color: PROVIDER_BRAND_COLORS.beatport, fontSize: '1rem', cursor: 'default', fontWeight: 600 }}>
        B
      </span>
    );
  }

  if (status === 'not_found') {
    return (
      <button
        className="btn btn-sm"
        style={{ background: 'var(--color-warning)', color: 'white', padding: '0.125rem 0.375rem', fontSize: '0.7rem', lineHeight: 1.2 }}
        onClick={onNotFound}
        title="Missing from Beatport - click for details"
      >
        B?
      </button>
    );
  }

  if (status === 'error') {
    return (
      <span
        title={`Beatport error: ${syncResult?.error || 'unknown'}`}
        style={{ color: 'var(--color-danger)', fontSize: '0.875rem', cursor: 'default' }}
      >
        B!
      </span>
    );
  }

  // No result yet
  return null;
}

