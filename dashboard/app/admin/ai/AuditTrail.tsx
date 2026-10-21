'use client';

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { AdminLlmAuditFilters } from '@/lib/api';
import type { LlmAdminAudit, LlmAdminConnector } from '@/lib/api/types';

const PAGE_SIZE = 50;
const EVENT_TYPES = [
  { value: 'connector_created', label: 'Connector created' },
  { value: 'connector_credentials_rotated', label: 'Credentials rotated' },
  { value: 'connector_deleted', label: 'Connector deleted' },
  { value: 'connector_revoked_by_admin', label: 'Revoked by admin' },
  { value: 'auth_invalid_observed', label: 'Auth invalid observed' },
  { value: 'policy_changed', label: 'Policy changed' },
  { value: 'connector_health_check', label: 'Health check' },
  { value: 'fallback_triggered:rate_limited', label: 'Fallback — rate limited' },
  { value: 'fallback_triggered:auth_invalid', label: 'Fallback — auth invalid' },
  { value: 'fallback_triggered:provider_unavailable', label: 'Fallback — provider unavailable' },
  { value: 'fallback_triggered:quota_exceeded', label: 'Fallback — quota exceeded' },
];
const DAY_OPTIONS = [
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
  { value: 365, label: 'Last year' },
  { value: 3650, label: 'All time' },
];

function formatTimestamp(ts: string | null | undefined): string {
  return ts ? new Date(ts).toLocaleString() : '—';
}

function PlainHeader({ label }: { label: string }) {
  return <th style={{ textAlign: 'left', padding: '0.5rem', borderBottom: '1px solid var(--border)' }}>{label}</th>;
}

export function AuditTrail({ connectors }: { connectors: LlmAdminConnector[] }) {
  const [audit, setAudit] = useState<LlmAdminAudit | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [eventType, setEventType] = useState('');
  const [actorId, setActorId] = useState('');
  const [connectorId, setConnectorId] = useState('');
  const [days, setDays] = useState(30);
  const [page, setPage] = useState(0);
  const [exporting, setExporting] = useState(false);

  const buildFilters = useCallback(
    (overrides: Partial<AdminLlmAuditFilters> = {}): AdminLlmAuditFilters => {
      const filters: AdminLlmAuditFilters = { days, limit: PAGE_SIZE, offset: page * PAGE_SIZE };
      if (eventType) filters.event_type = eventType;
      const parsedActor = Number.parseInt(actorId, 10);
      if (actorId && !Number.isNaN(parsedActor)) filters.actor_user_id = parsedActor;
      const parsedConnector = Number.parseInt(connectorId, 10);
      if (connectorId && !Number.isNaN(parsedConnector)) filters.target_connector_id = parsedConnector;
      return { ...filters, ...overrides };
    },
    [days, page, eventType, actorId, connectorId],
  );

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    api.getAdminLlmAudit(buildFilters())
      .then((data) => { if (active) setAudit(data); })
      .catch((err) => { if (active) setError(err instanceof Error ? err.message : 'Failed to load audit events'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [buildFilters]);

  const updateFilter = (apply: () => void) => {
    setPage(0);
    apply();
  };

  const exportCsv = async () => {
    setExporting(true);
    setError('');
    try {
      const blob = await api.downloadAdminLlmAuditCsv(buildFilters());
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'llm-audit-events.csv';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="card" style={{ marginTop: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <h2 style={{ marginTop: 0, marginBottom: 0 }}>Audit trail</h2>
        <button className="btn" onClick={exportCsv} disabled={exporting}>{exporting ? 'Exporting…' : 'Export CSV'}</button>
      </div>
      <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '0.5rem' }}>
        Credential lifecycle events for every connector. Export honors the active filters.
      </p>
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '1rem' }}>
        <div className="form-group" style={{ margin: 0 }}>
          <label htmlFor="audit-event-type">Event type</label>
          <select id="audit-event-type" className="input" value={eventType} onChange={(e) => updateFilter(() => setEventType(e.target.value))}>
            <option value="">All event types</option>
            {EVENT_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
          </select>
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label htmlFor="audit-actor">Actor user ID</label>
          <input id="audit-actor" type="number" min={1} className="input" style={{ maxWidth: '160px' }} placeholder="Any" value={actorId} onChange={(e) => updateFilter(() => setActorId(e.target.value))} />
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label htmlFor="audit-connector">Connector</label>
          <select id="audit-connector" className="input" value={connectorId} onChange={(e) => updateFilter(() => setConnectorId(e.target.value))}>
            <option value="">All connectors</option>
            {connectors.map((connector) => <option key={connector.id} value={connector.id}>{connector.dj_username} — {connector.display_name}</option>)}
          </select>
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label htmlFor="audit-days">Date range</label>
          <select id="audit-days" className="input" value={days} onChange={(e) => updateFilter(() => setDays(Number.parseInt(e.target.value, 10)))}>
            {DAY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </div>
      </div>
      {error && <div style={{ color: 'var(--color-danger)', marginTop: '1rem' }}>{error}</div>}
      {loading && !audit ? (
        <p style={{ color: 'var(--text-secondary)', marginTop: '1rem' }}>Loading audit events…</p>
      ) : audit && audit.rows.length === 0 ? (
        <p style={{ color: 'var(--text-secondary)', marginTop: '1rem' }}>No audit events match these filters.</p>
      ) : audit ? (
        <>
          <div style={{ overflowX: 'auto', marginTop: '1rem' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>{['Timestamp', 'Actor', 'Event type', 'Connector', 'Notes'].map((h) => <PlainHeader key={h} label={h} />)}</tr></thead>
              <tbody>{audit.rows.map((row) => (
                <tr key={row.id}>
                  <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>{formatTimestamp(row.created_at)}</td>
                  <td style={{ padding: '0.5rem' }}>{row.actor_username}</td>
                  <td style={{ padding: '0.5rem' }}>{row.event_type}</td>
                  <td style={{ padding: '0.5rem' }}>{row.target_connector_display_name ?? '—'}</td>
                  <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>{row.notes ?? '—'}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '1rem' }}>
            <button className="btn" disabled={page === 0 || loading} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              {audit.total === 0 ? '0 events' : `${audit.offset + 1}–${Math.min(audit.offset + audit.rows.length, audit.total)} of ${audit.total}`}
            </span>
            <button className="btn" disabled={loading || audit.offset + PAGE_SIZE >= audit.total} onClick={() => setPage((value) => value + 1)}>Next</button>
          </div>
        </>
      ) : null}
    </div>
  );
}
