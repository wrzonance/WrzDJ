'use client';

import { useState } from 'react';
import type { RequestStatus, SongRequest } from '@/lib/api/types';
import type { StatusFilter } from '@/lib/requests/types';
import { SORT_FIELDS } from '@/lib/requests/request-sort';
import type { RequestQueueToolbarProps, RequestRowActions } from './requestQueueTypes';

const REQUEST_STATUS_FILTERS = {
  new: 'new',
  accepted: 'accepted',
  playing: 'playing',
  played: 'played',
  rejected: 'rejected',
} satisfies { [Status in RequestStatus]: Status };

const STATUS_FILTERS: readonly StatusFilter[] = ['all', ...Object.values(REQUEST_STATUS_FILTERS)];

interface RequestQueueToolbarComponentProps {
  toolbar: RequestQueueToolbarProps;
  requests: SongRequest[];
  advancedMode: boolean;
  onAdvancedModeChange: (enabled: boolean) => void;
  isExpiredOrArchived: boolean;
  onRefreshMetadata?: RequestRowActions['onRefreshMetadata'];
}

export function RequestQueueToolbar({
  toolbar,
  requests,
  advancedMode,
  onAdvancedModeChange,
  isExpiredOrArchived,
  onRefreshMetadata,
}: RequestQueueToolbarComponentProps) {
  const {
    acceptingAll, onAcceptAll, onRejectAll, onBulkDelete, onEnrichAll, rejectingAll,
    sortField, sortDirection, onSortFieldChange, onSortDirectionToggle,
    filter, onFilterChange, statusCounts,
  } = toolbar;
  const [deletingAll, setDeletingAll] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [enrichingAll, setEnrichingAll] = useState(false);
  const [enrichmentError, setEnrichmentError] = useState<string | null>(null);

  const handleDeleteAll = async () => {
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
      for (const { id } of requests) {
        await onRefreshMetadata?.(id);
      }
    } finally {
      setRefreshingAll(false);
    }
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
      <div className="tabs" style={{ marginBottom: 0 }}>
        {STATUS_FILTERS.map((status) => (
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
          onChange={(e) => onSortFieldChange(e.target.value as typeof sortField)}
          style={{ width: 'auto', padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
        >
          {SORT_FIELDS.map((field) => (
            <option key={field.value} value={field.value}>{field.label}</option>
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
              onChange={(e) => onAdvancedModeChange(e.target.checked)}
              style={{ accentColor: 'var(--color-accent-checkbox)' }}
            />
            Advanced
          </label>
          {statusCounts.new > 0 && (
            <>
              <button className="btn btn-success btn-sm" onClick={onAcceptAll} disabled={acceptingAll}>
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
                    setEnrichmentError(null);
                    try {
                      const { queued, remaining } = await onEnrichAll();
                      if (queued === 0) {
                        alert('All tracks already have BPM, key, and genre.');
                      } else if (remaining > 0) {
                        alert(`Queued ${queued} tracks. ${remaining} more remaining — wait ~1 min for these to finish, then click again.`);
                      } else {
                        alert(`Queued enrichment for ${queued} track${queued === 1 ? '' : 's'}. Metadata will fill in over the next minute.`);
                      }
                    } catch {
                      setEnrichmentError('Could not queue metadata enrichment. Please try again.');
                    } finally {
                      setEnrichingAll(false);
                    }
                  }}
                  disabled={enrichingAll}
                >
                  {enrichingAll ? 'Queuing…' : 'Enrich All'}
                </button>
              )}
              {enrichmentError && <span role="alert">{enrichmentError}</span>}
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
  );
}
