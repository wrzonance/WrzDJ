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
import { formatRequestTimestamp } from '@/lib/format-time';
import { formatPriorityScore, getPriorityScoreColor } from '@/lib/priority-score';
import { PUBLIC_PAGE_MAX } from '@/lib/api';
import { SORT_FIELDS } from '@/lib/request-sort';
import type { RequestSort, SortDirection } from '@/lib/api-types';

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
  // Sort + growing-window pagination (issue #478). The server sorts
  // authoritatively by field+direction and filters by status; this component is
  // fully controlled — `requests` is the server-filtered page rendered as-is.
  sortField: RequestSort;
  sortDirection: SortDirection;
  onSortFieldChange: (field: RequestSort) => void;
  onSortDirectionToggle: () => void;
  total: number;
  onLoadMore: (status?: string) => Promise<void>;
  // Active status filter (lifted to the page so the poll re-fetches with it) and
  // true per-status totals for the tabs (independent of the loaded window).
  filter: StatusFilter;
  onFilterChange: (filter: StatusFilter) => void;
  statusCounts: Record<StatusFilter, number>;
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
  sortField,
  sortDirection,
  onSortFieldChange,
  onSortDirectionToggle,
  total,
  onLoadMore,
  filter,
  onFilterChange,
  statusCounts,
}: RequestQueueSectionProps) {
  const [advancedMode, setAdvancedMode] = useState(false);
  const [deletingAll, setDeletingAll] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [enrichingAll, setEnrichingAll] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  // Compute BPM context from the DJ's active set (accepted + playing)
  // so badges show proximity relative to the current musical direction
  const bpmContext = useMemo(() => {
    const activeBpms = requests
      .filter((r) => r.status === 'accepted' || r.status === 'playing')
      .map((r) => r.bpm)
      .filter((b): b is number => b != null);
    return computeBpmContext(activeBpms);
  }, [requests]);

  // The server returns rows already sorted AND filtered by status (issue #478),
  // so this component renders `requests` as-is — never reordering or filtering.
  const handleDeleteAll = async () => {
    // Bulk delete targets the whole server-side filtered set (true count), not
    // just the loaded window. "all" deletes every status.
    const count = filter === 'all' ? statusCounts.all : statusCounts[filter];
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
    if (requests.length === 0) return;
    setRefreshingAll(true);
    try {
      const ids = requests.map((r) => r.id);
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
              onClick={() => onFilterChange(status)}
            >
              {status.charAt(0).toUpperCase() + status.slice(1)} ({statusCounts[status]})
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', marginLeft: 'auto' }}>
          <label
            htmlFor="request-sort-field"
            style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}
          >
            Sort
          </label>
          <select
            id="request-sort-field"
            className="input"
            aria-label="Sort requests by"
            value={sortField}
            onChange={(e) => onSortFieldChange(e.target.value as RequestSort)}
            style={{ width: 'auto', padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
          >
            {SORT_FIELDS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-sm"
            style={{ background: 'var(--surface-raised)', fontSize: '0.75rem', minWidth: '2rem' }}
            onClick={onSortDirectionToggle}
            aria-label={`Sort direction: ${sortDirection === 'asc' ? 'ascending' : 'descending'}`}
            title={sortDirection === 'asc' ? 'Ascending' : 'Descending'}
          >
            {sortDirection === 'asc' ? '↑' : '↓'}
          </button>
        </div>
        {!isExpiredOrArchived && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
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
                  disabled={refreshingAll || requests.length === 0}
                >
                  {refreshingAll ? 'Refreshing...' : 'Refresh All'}
                </button>
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--color-danger-subtle)', fontSize: '0.7rem' }}
                  onClick={handleDeleteAll}
                  disabled={deletingAll || (filter === 'all' ? statusCounts.all : statusCounts[filter]) === 0}
                >
                  {deletingAll ? 'Deleting...' : 'Delete All'}
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {requests.length === 0 ? (
        <div className="card" style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--text-secondary)' }}>
            {filter === 'all'
              ? 'No requests yet. Share the QR code with your guests!'
              : `No ${filter} requests.`}
          </p>
        </div>
      ) : (
        <div className="request-list scrollable-list" style={{ marginBottom: '1rem' }}>
          {requests.map((request) => (
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
                    {formatRequestTimestamp(request.created_at)}
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
                  {sortField === 'best_match' && request.priority_score != null && (
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

      {(() => {
        // `requests` is the server's filtered page and `total` is that filter's
        // true count, so "Showing X of Y" is honest per-filter. Hide once
        // everything is loaded or we hit the cap.
        const loaded = requests.length;
        const hasMore = loaded < total && loaded < PUBLIC_PAGE_MAX;
        if (loaded === 0) return null;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Showing {loaded} of {total}
            </span>
            {hasMore && (
              <button
                type="button"
                className="btn btn-sm"
                style={{ background: 'var(--surface-raised)' }}
                disabled={loadingMore}
                onClick={async () => {
                  setLoadingMore(true);
                  try {
                    await onLoadMore(filter === 'all' ? undefined : filter);
                  } finally {
                    setLoadingMore(false);
                  }
                }}
              >
                {loadingMore ? 'Loading…' : 'Load More'}
              </button>
            )}
          </div>
        );
      })()}
    </>
  );
}
