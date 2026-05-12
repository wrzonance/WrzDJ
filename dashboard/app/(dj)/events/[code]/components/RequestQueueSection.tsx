'use client';

import { useMemo, useState } from 'react';
import { SongRequest } from '@/lib/api';
import { Tooltip } from '@/components/Tooltip';
import { StatusFilter } from './types';
import { SyncStatusBadges } from './SyncStatusBadges';
import { KeyBadge, BpmBadge, GenreBadge } from '@/components/MusicBadges';
import { PreviewPlayer } from '@/components/PreviewPlayer';
import { computeBpmContext } from '@/lib/bpm-stats';
import { getRequestEmphasisStyle } from '@/lib/request-emphasis';
import { safeExternalUrl } from '@/lib/safe-url';
import { getVoteHeatStyle } from '@/lib/vote-heat';
import { formatPriorityScore, getPriorityScoreColor } from '@/lib/priority-score';
import type { SortMode } from '@/lib/priority-score';

interface RequestQueueSectionProps {
  requests: SongRequest[];
  isExpiredOrArchived: boolean;
  connectedServices: string[];
  bridgeConnected?: boolean;
  updating: number | null;
  acceptingAll: boolean;
  syncingRequest: number | null;
  onUpdateStatus: (requestId: number, status: string) => void;
  onAcceptAll: () => void;
  onSyncToTidal: (requestId: number) => void;
  onOpenTidalPicker: (requestId: number) => void;
  onScrollToSyncReport?: (requestId: number) => void;
  onRejectAll?: () => Promise<void>;
  onBulkDelete?: (status?: string) => Promise<void>;
  onDeleteRequest?: (requestId: number) => Promise<void>;
  onRefreshMetadata?: (requestId: number) => Promise<void>;
  onEnrichAll?: () => Promise<{ queued: number; remaining: number }>;
  rejectingAll?: boolean;
  deletingRequest?: number | null;
  refreshingRequest?: number | null;
  sortMode: SortMode;
  onSortModeChange: (mode: SortMode) => void;
}

export function RequestQueueSection({
  requests,
  isExpiredOrArchived,
  connectedServices,
  bridgeConnected,
  updating,
  acceptingAll,
  syncingRequest,
  onUpdateStatus,
  onAcceptAll,
  onSyncToTidal,
  onOpenTidalPicker,
  onScrollToSyncReport,
  onRejectAll,
  onBulkDelete,
  onDeleteRequest,
  onRefreshMetadata,
  onEnrichAll,
  rejectingAll,
  deletingRequest,
  refreshingRequest,
  sortMode,
  onSortModeChange,
}: RequestQueueSectionProps) {
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [advancedMode, setAdvancedMode] = useState(false);
  const [deletingAll, setDeletingAll] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [enrichingAll, setEnrichingAll] = useState(false);

  const statusCounts = useMemo(() => {
    const counts = { all: requests.length, new: 0, accepted: 0, playing: 0, played: 0, rejected: 0 };
    for (const r of requests) {
      const s = r.status as keyof typeof counts;
      if (s in counts) counts[s]++;
    }
    return counts;
  }, [requests]);

  // Compute BPM context from the DJ's active set (accepted + playing)
  // so badges show proximity relative to the current musical direction
  const bpmContext = useMemo(() => {
    const activeBpms = requests
      .filter((r) => r.status === 'accepted' || r.status === 'playing')
      .map((r) => r.bpm)
      .filter((b): b is number => b != null);
    return computeBpmContext(activeBpms);
  }, [requests]);

  const filteredRequests = useMemo(() => {
    const filtered = requests.filter((r) => (filter === 'all' ? true : r.status === filter));
    // In priority mode, API returns pre-sorted results — preserve that order
    if (sortMode === 'priority') return filtered;
    if (filter === 'all') {
      return [...filtered].sort((a, b) => {
        const aBottom = a.status === 'played' ? 1 : 0;
        const bBottom = b.status === 'played' ? 1 : 0;
        return aBottom - bBottom;
      });
    }
    return filtered;
  }, [requests, filter, sortMode]);

  const handleDeleteAll = async () => {
    const count = filteredRequests.length;
    if (count === 0) return;
    if (!window.confirm(`Delete all ${count} ${filter === 'all' ? '' : filter + ' '}request${count === 1 ? '' : 's'}? This cannot be undone.`)) return;
    setDeletingAll(true);
    try {
      await onBulkDelete?.(filter === 'all' ? undefined : filter);
    } finally {
      setDeletingAll(false);
    }
  };

  const handleRefreshAll = async () => {
    if (filteredRequests.length === 0) return;
    setRefreshingAll(true);
    try {
      const ids = filteredRequests.map((r) => r.id);
      for (const id of ids) {
        await onRefreshMetadata?.(id);
      }
    } finally {
      setRefreshingAll(false);
    }
  };

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
        <div className="tabs" style={{ marginBottom: 0 }}>
          {(['all', 'new', 'accepted', 'playing', 'played', 'rejected'] as StatusFilter[]).map((status) => (
            <button
              key={status}
              className={`tab ${filter === status ? 'active' : ''}`}
              onClick={() => setFilter(status)}
            >
              {status.charAt(0).toUpperCase() + status.slice(1)} ({statusCounts[status]})
            </button>
          ))}
        </div>
        {!isExpiredOrArchived && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginLeft: 'auto' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', color: sortMode === 'priority' ? 'var(--color-success)' : 'var(--text-secondary)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={sortMode === 'priority'}
                onChange={(e) => onSortModeChange(e.target.checked ? 'priority' : 'chronological')}
                style={{ accentColor: 'var(--color-success)' }}
              />
              Best Match
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={advancedMode}
                onChange={(e) => setAdvancedMode(e.target.checked)}
                style={{ accentColor: 'var(--color-accent-checkbox)' }}
              />
              Advanced
            </label>
            {statusCounts.new > 0 && (
              <>
                <button
                  className="btn btn-success btn-sm"
                  onClick={onAcceptAll}
                  disabled={acceptingAll}
                >
                  {acceptingAll ? 'Accepting...' : `Accept All (${statusCounts.new})`}
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => {
                    if (window.confirm(`Reject all ${statusCounts.new} new request${statusCounts.new === 1 ? '' : 's'}?`)) {
                      onRejectAll?.();
                    }
                  }}
                  disabled={rejectingAll}
                >
                  {rejectingAll ? 'Rejecting...' : `Reject All (${statusCounts.new})`}
                </button>
              </>
            )}
            {advancedMode && (
              <>
                {onEnrichAll && (
                  <button
                    className="btn btn-sm"
                    style={{ background: 'var(--color-log-info-bg)', fontSize: '0.7rem' }}
                    onClick={async () => {
                      setEnrichingAll(true);
                      try {
                        const { queued, remaining } = await onEnrichAll();
                        if (queued === 0) {
                          alert('All tracks already have BPM, key, and genre.');
                        } else if (remaining > 0) {
                          alert(`Queued ${queued} tracks. ${remaining} more remaining — wait ~1 min for these to finish, then click again.`);
                        } else {
                          alert(`Queued enrichment for ${queued} track${queued === 1 ? '' : 's'}. Metadata will fill in over the next minute.`);
                        }
                      } finally {
                        setEnrichingAll(false);
                      }
                    }}
                    disabled={enrichingAll}
                  >
                    {enrichingAll ? 'Queuing…' : 'Enrich All'}
                  </button>
                )}
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--surface-raised)', fontSize: '0.7rem' }}
                  onClick={handleRefreshAll}
                  disabled={refreshingAll || filteredRequests.length === 0}
                >
                  {refreshingAll ? 'Refreshing...' : 'Refresh All'}
                </button>
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--color-danger-subtle)', fontSize: '0.7rem' }}
                  onClick={handleDeleteAll}
                  disabled={deletingAll || filteredRequests.length === 0}
                >
                  {deletingAll ? 'Deleting...' : 'Delete All'}
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {filteredRequests.length === 0 ? (
        <div className="card" style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--text-secondary)' }}>
            {filter === 'all'
              ? 'No requests yet. Share the QR code with your guests!'
              : `No ${filter} requests.`}
          </p>
        </div>
      ) : (
        <div className="request-list scrollable-list" style={{ marginBottom: '1rem' }}>
          {filteredRequests.map((request) => (
            <div
              key={request.id}
              id={`request-${request.id}`}
              className="request-item"
              style={{
                ...(() => {
                  const emphasis = getRequestEmphasisStyle(request.status);
                  const heat = getVoteHeatStyle(request.vote_count);
                  return {
                    ...emphasis,
                    ...heat,
                    // Status emphasis background takes priority over vote heat
                    ...(emphasis.background ? { background: emphasis.background } : {}),
                  };
                })(),
              }}
            >
              {request.artwork_url ? (
                <img
                  src={request.artwork_url}
                  alt=""
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: '0.25rem',
                    objectFit: 'cover',
                    flexShrink: 0,
                    marginRight: '0.625rem',
                  }}
                />
              ) : (
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: '0.25rem',
                    background: 'var(--border-subtle)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    marginRight: '0.625rem',
                    fontSize: '1rem',
                    color: 'var(--text-tertiary)',
                  }}
                >
                  ♪
                </div>
              )}
              <div className="request-info">
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.375rem' }}>
                  <h3 style={{ margin: 0 }}>
                    {request.song_title}
                  </h3>
                  {safeExternalUrl(request.source_url) && (
                    <a
                      href={safeExternalUrl(request.source_url)}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: '0.75rem', flexShrink: 0 }}
                    >
                      ↗
                    </a>
                  )}
                </div>
                <p>{request.artist}</p>
                {(request.bpm || request.musical_key || request.genre) && (
                  <div style={{
                    display: 'flex', gap: '0.375rem', marginTop: '0.25rem',
                    flexWrap: 'wrap', alignItems: 'center',
                  }}>
                    <BpmBadge
                      bpm={request.bpm}
                      avgBpm={bpmContext.average}
                      isOutlier={request.bpm != null ? bpmContext.isOutlier(request.bpm) : false}
                    />
                    <KeyBadge musicalKey={request.musical_key} />
                    <GenreBadge genre={request.genre} />
                  </div>
                )}
                {request.nickname && (
                  <div className="request-nickname">
                    <span className="nickname-icon">&#128100;</span> {request.nickname}
                  </div>
                )}
                {request.note && <div className="note">{request.note}</div>}
                <PreviewPlayer data={{
                  source: request.source,
                  sourceUrl: request.source_url,
                }} />
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem' }}>
                  <p style={{ fontSize: '0.75rem', margin: 0 }}>
                    {new Date(request.created_at).toLocaleTimeString()}
                  </p>
                  {request.vote_count > 0 && (
                    <span
                      style={{
                        background: request.vote_count >= 5 ? 'var(--color-warning)' : 'var(--color-primary)',
                        color: '#fff',
                        padding: '0.125rem 0.5rem',
                        borderRadius: '1rem',
                        fontSize: '0.7rem',
                        fontWeight: 600,
                      }}
                    >
                      {request.vote_count} {request.vote_count === 1 ? 'vote' : 'votes'}
                    </span>
                  )}
                  {sortMode === 'priority' && request.priority_score != null && (
                    <Tooltip description="Combines votes, wait time, harmonic compatibility, and BPM energy match" delay={100}>
                      <span
                        style={{
                          background: getPriorityScoreColor(request.priority_score),
                          color: '#fff',
                          padding: '0.125rem 0.5rem',
                          borderRadius: '1rem',
                          fontSize: '0.7rem',
                          fontWeight: 600,
                          cursor: 'help',
                        }}
                      >
                        {formatPriorityScore(request.priority_score)}
                      </span>
                    </Tooltip>
                  )}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                <SyncStatusBadges
                  request={request}
                  connectedServices={connectedServices}
                  syncingRequest={syncingRequest}
                  onSyncToTidal={onSyncToTidal}
                  onOpenTidalPicker={onOpenTidalPicker}
                  onScrollToSyncReport={onScrollToSyncReport}
                />
                <span className={`badge badge-${request.status}`}>{request.status === 'playing' ? 'manually playing' : request.status}</span>
                {!isExpiredOrArchived && (
                  <div className="request-actions">
                    {request.status === 'new' && (
                      <>
                        <button
                          className="btn btn-success btn-sm"
                          onClick={() => onUpdateStatus(request.id, 'accepted')}
                          disabled={updating !== null}
                        >
                          Accept
                        </button>
                        <button
                          className="btn btn-danger btn-sm"
                          onClick={() => onUpdateStatus(request.id, 'rejected')}
                          disabled={updating !== null}
                        >
                          Reject
                        </button>
                      </>
                    )}
                    {request.status === 'accepted' && (
                      <>
                        {(!bridgeConnected || advancedMode) && (
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={() => onUpdateStatus(request.id, 'playing')}
                            disabled={updating !== null}
                          >
                            Mark Playing
                          </button>
                        )}
                        <button
                          className="btn btn-danger btn-sm"
                          onClick={() => onUpdateStatus(request.id, 'rejected')}
                          disabled={updating !== null}
                        >
                          Reject
                        </button>
                      </>
                    )}
                    {request.status === 'playing' && (
                      <button
                        className="btn btn-warning btn-sm"
                        onClick={() => onUpdateStatus(request.id, 'played')}
                        disabled={updating !== null}
                      >
                        Played
                      </button>
                    )}
                    {advancedMode && (
                      <>
                        <Tooltip description="Re-fetch BPM, key, and genre from external services">
                          <button
                            className="btn btn-sm"
                            style={{ background: 'var(--surface-raised)', fontSize: '0.7rem' }}
                            onClick={() => onRefreshMetadata?.(request.id)}
                            disabled={refreshingRequest === request.id}
                          >
                            {refreshingRequest === request.id ? '...' : 'Refresh'}
                          </button>
                        </Tooltip>
                        <button
                          className="btn btn-sm"
                          style={{ background: 'var(--color-danger-subtle)', fontSize: '0.7rem' }}
                          onClick={() => {
                            if (window.confirm(`Delete "${request.song_title}" by ${request.artist}?`)) {
                              onDeleteRequest?.(request.id);
                            }
                          }}
                          disabled={deletingRequest === request.id}
                        >
                          {deletingRequest === request.id ? '...' : 'Delete'}
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
