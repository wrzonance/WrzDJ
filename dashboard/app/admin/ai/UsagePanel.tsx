'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { LlmAdminUsage } from '@/lib/api/types';
import { TYPE_LABELS } from './OrgConnectorSection';

function PlainHeader({ label }: { label: string }) {
  return <th style={{ textAlign: 'left', padding: '0.5rem', borderBottom: '1px solid var(--border)' }}>{label}</th>;
}

export function UsagePanel() {
  const [usage, setUsage] = useState<LlmAdminUsage | null>(null);
  const [loadState, setLoadState] = useState<'loading' | 'loaded' | 'error'>('loading');
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    let active = true;
    setLoadState('loading');
    api.getAdminLlmUsage(30).then((data) => {
      if (!active) return;
      setUsage(data);
      setLoadState('loaded');
    }).catch(() => {
      if (active) setLoadState('error');
    });
    return () => { active = false; };
  }, [retryCount]);

  if (loadState === 'loading') {
    return (
      <div className="card" style={{ marginTop: '2rem' }}>
        <h2 style={{ marginTop: 0 }}>Usage — last 30 days</h2>
        <p style={{ color: 'var(--text-secondary)' }}>Loading usage…</p>
      </div>
    );
  }
  if (loadState === 'error') {
    return (
      <div className="card" style={{ marginTop: '2rem' }}>
        <h2 style={{ marginTop: 0 }}>Usage — last 30 days</h2>
        <p role="alert" style={{ color: 'var(--text-secondary)' }}>Failed to load usage.</p>
        <button className="btn" onClick={() => setRetryCount((count) => count + 1)}>
          Try again
        </button>
      </div>
    );
  }
  if (!usage) return null;
  return (
    <div className="card" style={{ marginTop: '2rem' }}>
      <h2 style={{ marginTop: 0 }}>Usage — last {usage.days} days</h2>
      {usage.rows.length === 0 ? (
        <p style={{ color: 'var(--text-secondary)' }}>No calls yet.</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>{['DJ', 'Connector', 'Calls', 'Tokens in', 'Tokens out', 'Error rate'].map((h) => <PlainHeader key={h} label={h} />)}</tr></thead>
            <tbody>{usage.rows.map((row) => (
              <tr key={row.connector_id}>
                <td style={{ padding: '0.5rem' }}>{row.dj_username}</td>
                <td style={{ padding: '0.5rem' }}>{row.display_name} <span style={{ color: 'var(--text-secondary)' }}>· {TYPE_LABELS[row.connector_type] ?? row.connector_type}</span></td>
                <td style={{ padding: '0.5rem' }}>{row.total_calls}</td>
                <td style={{ padding: '0.5rem' }}>{row.total_tokens_in}</td>
                <td style={{ padding: '0.5rem' }}>{row.total_tokens_out}</td>
                <td style={{ padding: '0.5rem' }}>{(row.error_rate * 100).toFixed(1)}%</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
