'use client';

import { useState } from 'react';
import type { ActivityLogEntry } from '@/lib/api-types';

interface ActivityLogPanelProps {
  entries: ActivityLogEntry[];
}

export function ActivityLogPanel({ entries }: ActivityLogPanelProps) {
  const [expanded, setExpanded] = useState(false);

  const warningCount = entries.filter(
    (e) => e.level === 'warning' || e.level === 'error'
  ).length;

  return (
    <div className="card">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded((prev) => !prev)}
      >
        <h3 style={{ margin: 0 }}>
          Activity Log
          {warningCount > 0 && (
            <span
              style={{
                marginLeft: '0.75rem',
                fontSize: '0.75rem',
                padding: '0.125rem 0.5rem',
                borderRadius: '4px',
                background: 'var(--color-warning-subtle, rgba(120,53,15,0.2))',
                color: 'var(--color-warning, #fbbf24)',
              }}
            >
              {warningCount} warning{warningCount !== 1 ? 's' : ''}
            </span>
          )}
        </h3>
        <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          {expanded ? 'Collapse' : 'Expand'}
        </span>
      </div>

      {expanded && (
        <div className="activity-log" style={{ marginTop: '1rem' }}>
          {entries.length === 0 ? (
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              No recent activity
            </p>
          ) : (
            entries.map((entry) => (
              <div key={entry.id} className="log-entry">
                <span
                  style={{
                    color: 'var(--text-secondary)',
                    fontSize: '0.75rem',
                    whiteSpace: 'nowrap',
                    minWidth: '140px',
                  }}
                >
                  {new Date(entry.created_at).toLocaleString()}
                </span>
                <span className={`log-level-${entry.level}`}>
                  {entry.level}
                </span>
                <span className="log-source">{entry.source}</span>
                <span style={{ color: 'var(--text)' }}>{entry.message}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
