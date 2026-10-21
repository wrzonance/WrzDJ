'use client';

import { useMemo, useState } from 'react';
import type { SongRequest } from '@/lib/api/types';
import { PUBLIC_PAGE_MAX } from '@/lib/api';
import { computeBpmContext } from '@/lib/bpm-stats';
import { REQUEST_LOAD_CAP } from '@/lib/load-all-pages';
import type { RequestQueueToolbarProps, RequestRowActions } from './requestQueueTypes';
import { RequestQueueToolbar } from './RequestQueueToolbar';
import { RequestQueueRow } from './RequestQueueRow';

interface RequestQueueSectionProps {
  requests: SongRequest[];
  isExpiredOrArchived: boolean;
  toolbar: RequestQueueToolbarProps;
  rowActions: RequestRowActions;
}

export function RequestQueueSection({
  requests,
  isExpiredOrArchived,
  toolbar,
  rowActions,
}: RequestQueueSectionProps) {
  const [advancedMode, setAdvancedMode] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const { filter, total, filteredTotal = total, onLoadMore, capped } = toolbar;

  // BPM badges are contextualized against the DJ's active set.
  const bpmContext = useMemo(() => {
    const activeBpms = requests
      .filter((request) => request.status === 'accepted' || request.status === 'playing')
      .map((request) => request.bpm)
      .filter((bpm): bpm is number => bpm != null);
    return computeBpmContext(activeBpms);
  }, [requests]);

  return (
    <>
      <RequestQueueToolbar
        toolbar={toolbar}
        requests={requests}
        advancedMode={advancedMode}
        onAdvancedModeChange={setAdvancedMode}
        isExpiredOrArchived={isExpiredOrArchived}
        onRefreshMetadata={rowActions.onRefreshMetadata}
      />

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
            <RequestQueueRow
              key={request.id}
              request={request}
              actions={rowActions}
              presentation={{ isExpiredOrArchived, sortField: toolbar.sortField, advancedMode, bpmContext }}
            />
          ))}
        </div>
      )}

      {capped && (
        <div
          role="status"
          style={{
            padding: '0.625rem 0.875rem',
            marginBottom: '0.75rem',
            background: 'var(--surface-raised)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            fontSize: '0.8rem',
            color: 'var(--text-secondary)',
          }}
        >
          Showing {REQUEST_LOAD_CAP} of {total} requests — sort/filter limited to these.
        </div>
      )}

      {(() => {
        const loaded = requests.length;
        const hasMore = Boolean(onLoadMore) && loaded < total && loaded < PUBLIC_PAGE_MAX;
        if (loaded === 0) return null;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Showing {loaded} of {filteredTotal}
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
                    await onLoadMore?.(filter === 'all' ? undefined : filter);
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
