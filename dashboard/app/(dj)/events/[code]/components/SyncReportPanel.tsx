'use client';

import { useMemo, useEffect, useRef } from 'react';
import type { SongRequest, SyncResultEntry } from '@/lib/api-types';
import { Tooltip } from '@/components/Tooltip';
import { safeExternalUrl } from '@/lib/safe-url';

interface SyncReportPanelProps {
  requests: SongRequest[];
  connectedServices: string[];
  expanded: boolean;
  onToggleExpanded: () => void;
  focusedRequestId: number | null;
  onClearFocus: () => void;
  onRetrySync: (requestId: number) => void;
  onOpenTidalPicker: (requestId: number) => void;
  onOpenBeatportPicker: (requestId: number) => void;
}

function parseSyncResults(json: string | null): SyncResultEntry[] {
  if (!json) return [];
  try {
    return JSON.parse(json);
  } catch {
    return [];
  }
}

interface RequestSyncIssue {
  request: SongRequest;
  results: SyncResultEntry[];
}

export function SyncReportPanel({
  requests,
  connectedServices,
  expanded,
  onToggleExpanded,
  focusedRequestId,
  onClearFocus,
  onRetrySync,
  onOpenTidalPicker,
  onOpenBeatportPicker,
}: SyncReportPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const focusedRowRef = useRef<HTMLDivElement>(null);

  // Find requests with sync issues (not_found or error)
  const issueRequests = useMemo((): RequestSyncIssue[] => {
    return requests
      .filter((r) => r.status === 'accepted')
      .map((r) => ({
        request: r,
        results: parseSyncResults(r.sync_results_json),
      }))
      .filter(({ results }) =>
        results.some((entry) => entry.status === 'not_found' || entry.status === 'error')
      );
  }, [requests]);

  // Count totals for header summary
  const { missingCount, errorCount } = useMemo(() => {
    let missing = 0;
    let errors = 0;
    for (const { results } of issueRequests) {
      for (const entry of results) {
        if (entry.status === 'not_found') missing++;
        if (entry.status === 'error') errors++;
      }
    }
    return { missingCount: missing, errorCount: errors };
  }, [issueRequests]);

  // Auto-scroll to focused request when it changes
  useEffect(() => {
    if (focusedRequestId && expanded && focusedRowRef.current) {
      focusedRowRef.current.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
      // Clear focus after scroll animation
      const timer = setTimeout(() => onClearFocus(), 2000);
      return () => clearTimeout(timer);
    }
  }, [focusedRequestId, expanded, onClearFocus]);

  // Don't render if no connected services or no issues
  if (connectedServices.length === 0 || issueRequests.length === 0) {
    return null;
  }

  const summaryParts: string[] = [];
  if (missingCount > 0) {
    summaryParts.push(`${missingCount} track${missingCount !== 1 ? 's' : ''} missing`);
  }
  if (errorCount > 0) {
    summaryParts.push(`${errorCount} error${errorCount !== 1 ? 's' : ''}`);
  }
  const summaryText = summaryParts.join(', ');

  return (
    <div
      id="sync-report-panel"
      ref={panelRef}
      className="card"
      style={{ marginBottom: '1rem', padding: 0 }}
    >
      {/* Clickable header */}
      <button
        onClick={onToggleExpanded}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          width: '100%',
          padding: '0.75rem 1rem',
          background: 'transparent',
          border: 'none',
          color: 'var(--text)',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>Sync Report</span>
          <span
            style={{
              background: errorCount > 0 ? 'var(--color-danger-subtle)' : 'var(--color-warning-subtle)',
              color: errorCount > 0 ? 'var(--color-danger)' : 'var(--color-warning)',
              padding: '0.125rem 0.5rem',
              borderRadius: '1rem',
              fontSize: '0.7rem',
              fontWeight: 600,
            }}
          >
            {summaryText}
          </span>
        </div>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          {expanded ? '\u25B2' : '\u25BC'}
        </span>
      </button>

      {/* Expandable body */}
      {expanded && (
        <div style={{ padding: '0 1rem 1rem', maxHeight: '400px', overflowY: 'auto' }}>
          {issueRequests.map(({ request, results }) => {
            const isFocused = focusedRequestId === request.id;
            return (
              <div
                key={request.id}
                ref={isFocused ? focusedRowRef : undefined}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '0.5rem 0.75rem',
                  background: isFocused ? 'var(--color-primary-subtle)' : 'var(--surface-raised)',
                  borderRadius: '6px',
                  marginBottom: '0.375rem',
                  transition: 'background 0.3s ease',
                }}
              >
                {/* Track info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 500,
                      fontSize: '0.875rem',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {request.song_title}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>{request.artist}</div>
                </div>

                {/* Per-service status columns */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexShrink: 0 }}>
                  {connectedServices.map((service) => {
                    const entry = results.find((r) => r.service === service);
                    return (
                      <ServiceStatusCell
                        key={service}
                        service={service}
                        entry={entry}
                        requestId={request.id}
                        onRetry={onRetrySync}
                        onLink={service === 'tidal' ? onOpenTidalPicker : onOpenBeatportPicker}
                      />
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ServiceStatusCell({
  service,
  entry,
  requestId,
  onRetry,
  onLink,
}: {
  service: string;
  entry: SyncResultEntry | undefined;
  requestId: number;
  onRetry: (requestId: number) => void;
  onLink: (requestId: number) => void;
}) {
  const label = service.charAt(0).toUpperCase() + service.slice(1);

  if (!entry) {
    return (
      <span style={{ color: 'var(--text-tertiary)', fontSize: '0.75rem', minWidth: '80px', textAlign: 'center' }}>
        {label}: --
      </span>
    );
  }

  if (entry.status === 'added' || entry.status === 'matched') {
    const confidence = entry.confidence ? ` (${Math.round(entry.confidence * 100)}%)` : '';
    if (entry.url) {
      return (
        <Tooltip description={`View on ${label}`} delay={100}>
          <a
            href={safeExternalUrl(entry.url) ?? '#'}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'var(--color-success)', fontSize: '0.75rem', minWidth: '80px', textAlign: 'center', textDecoration: 'none' }}
          >
            {label}: Synced{confidence}
          </a>
        </Tooltip>
      );
    }
    return (
      <span style={{ color: 'var(--color-success)', fontSize: '0.75rem', minWidth: '80px', textAlign: 'center' }}>
        {label}: Synced{confidence}
      </span>
    );
  }

  if (entry.status === 'not_found') {
    return (
      <Tooltip description={`Click to link manually on ${label}`} delay={100}>
        <button
          onClick={() => onLink(requestId)}
          style={{
            background: 'var(--color-warning-subtle)',
            color: 'var(--color-warning)',
            border: 'none',
            padding: '0.125rem 0.5rem',
            borderRadius: '4px',
            fontSize: '0.7rem',
            cursor: 'pointer',
            minWidth: '80px',
            textAlign: 'center',
          }}
        >
          {label}: Missing
        </button>
      </Tooltip>
    );
  }

  if (entry.status === 'error') {
    return (
      <Tooltip description={`${label}: ${entry.error || 'Unknown error'} — click to retry`} delay={100}>
        <button
          onClick={() => onRetry(requestId)}
          style={{
            background: 'var(--color-danger-subtle)',
            color: 'var(--color-danger)',
            border: 'none',
            padding: '0.125rem 0.5rem',
            borderRadius: '4px',
            fontSize: '0.7rem',
            cursor: 'pointer',
            minWidth: '80px',
            textAlign: 'center',
          }}
        >
          {label}: Error
        </button>
      </Tooltip>
    );
  }

  return null;
}
