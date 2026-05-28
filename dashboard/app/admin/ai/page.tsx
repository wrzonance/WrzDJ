'use client';

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { AdminLlmAuditFilters } from '@/lib/api';
import type {
  AISettings,
  AIModelInfo,
  LlmAdminAudit,
  LlmAdminConnector,
  LlmAdminPolicy,
  LlmAdminUsage,
} from '@/lib/api-types';
import { useAdminPage } from '@/lib/useAdminPage';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';

const PAGE_ID = 'admin-ai';

const TYPE_LABELS: Record<string, string> = {
  openai_apikey: 'OpenAI',
  anthropic_apikey: 'Anthropic',
  openrouter_apikey: 'OpenRouter',
  xai_apikey: 'xAI',
  gemini_apikey: 'Gemini',
  openai_compatible: 'OpenAI-compatible',
  bedrock: 'AWS Bedrock',
  azure_openai: 'Azure OpenAI',
};

// Audit event types — mirrors AUDIT_* constants in models/llm_connector.py.
const AUDIT_EVENT_TYPES: Array<{ value: string; label: string }> = [
  { value: 'connector_created', label: 'Connector created' },
  { value: 'connector_credentials_rotated', label: 'Credentials rotated' },
  { value: 'connector_deleted', label: 'Connector deleted' },
  { value: 'connector_revoked_by_admin', label: 'Revoked by admin' },
  { value: 'auth_invalid_observed', label: 'Auth invalid observed' },
  { value: 'policy_changed', label: 'Policy changed' },
  { value: 'connector_health_check', label: 'Health check' },
  // Gateway auto-fallback events are written as `fallback_triggered:<trigger>`
  // (see services/llm/gateway.py). The audit filter is an exact event_type match,
  // so each trigger variant needs its own option to be filterable.
  { value: 'fallback_triggered:rate_limited', label: 'Fallback — rate limited' },
  { value: 'fallback_triggered:auth_invalid', label: 'Fallback — auth invalid' },
  { value: 'fallback_triggered:provider_unavailable', label: 'Fallback — provider unavailable' },
  { value: 'fallback_triggered:quota_exceeded', label: 'Fallback — quota exceeded' },
];

const AUDIT_PAGE_SIZE = 50;

// Map health-check status to a colour family. Active=green, transient/quota
// issues=amber, auth/error=red. ``null`` (never checked) is treated as
// "neutral" so the table doesn't scream red on first load.
const HEALTH_BADGE_STYLES: Record<
  string,
  { background: string; color: string; label: string }
> = {
  ok: { background: 'var(--color-success-subtle)', color: 'var(--color-success)', label: 'OK' },
  auth_invalid: {
    background: 'var(--color-danger-subtle)',
    color: 'var(--color-danger)',
    label: 'Auth invalid',
  },
  error: {
    background: 'var(--color-danger-subtle)',
    color: 'var(--color-danger)',
    label: 'Error',
  },
  rate_limited: {
    background: 'var(--color-warning-subtle, #2a2418)',
    color: 'var(--color-warning, #c08418)',
    label: 'Rate limited',
  },
  quota_exceeded: {
    background: 'var(--color-warning-subtle, #2a2418)',
    color: 'var(--color-warning, #c08418)',
    label: 'Quota exceeded',
  },
  provider_unavailable: {
    background: 'var(--color-warning-subtle, #2a2418)',
    color: 'var(--color-warning, #c08418)',
    label: 'Provider down',
  },
};

type ConnectorSortKey = 'dj_username' | 'last_used_at' | 'last_health_check_at';

function sortConnectors(
  rows: LlmAdminConnector[],
  sort: { key: ConnectorSortKey; direction: 'asc' | 'desc' },
): LlmAdminConnector[] {
  const factor = sort.direction === 'asc' ? 1 : -1;
  // Treat ``null`` timestamps as "always last" regardless of direction so an
  // admin sorting by recency doesn't get a wall of "never checked" rows at
  // the top — they live below the real signal.
  const tsValue = (v: string | null | undefined): number => {
    if (!v) return sort.direction === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;
    return new Date(v).getTime();
  };
  const copy = [...rows];
  copy.sort((a, b) => {
    if (sort.key === 'dj_username') {
      const cmp = a.dj_username.localeCompare(b.dj_username);
      if (cmp !== 0) return cmp * factor;
    } else {
      const cmp = tsValue(a[sort.key]) - tsValue(b[sort.key]);
      if (cmp !== 0) return cmp * factor;
    }
    // Stable tiebreak on id so re-renders don't reshuffle equal-keyed rows.
    return a.id - b.id;
  });
  return copy;
}

function PlainHeader({ label }: { label: string }) {
  return (
    <th
      style={{ textAlign: 'left', padding: '0.5rem', borderBottom: '1px solid var(--border-color)' }}
    >
      {label}
    </th>
  );
}

function SortableHeader({
  label,
  sortKey,
  activeKey,
  direction,
  onSort,
}: {
  label: string;
  sortKey: ConnectorSortKey;
  activeKey: ConnectorSortKey;
  direction: 'asc' | 'desc';
  onSort: (key: ConnectorSortKey, direction: 'asc' | 'desc') => void;
}) {
  const isActive = activeKey === sortKey;
  const arrow = isActive ? (direction === 'asc' ? '▲' : '▼') : '';
  return (
    <th
      onClick={() => {
        if (isActive) {
          onSort(sortKey, direction === 'asc' ? 'desc' : 'asc');
        } else {
          // First click on a new column goes to descending — newest-first is
          // the more useful default for both ``last_used_at`` and
          // ``last_health_check_at``.
          onSort(sortKey, 'desc');
        }
      }}
      style={{
        textAlign: 'left',
        padding: '0.5rem',
        borderBottom: '1px solid var(--border-color)',
        cursor: 'pointer',
        userSelect: 'none',
      }}
      aria-sort={isActive ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      {label}
      {arrow ? <span style={{ marginLeft: '0.25rem', fontSize: '0.75rem' }}>{arrow}</span> : null}
    </th>
  );
}

function HealthBadge({ status }: { status: string | null }) {
  if (!status) {
    return (
      <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Never checked</span>
    );
  }
  const style = HEALTH_BADGE_STYLES[status] ?? {
    background: 'var(--color-warning-subtle, #2a2418)',
    color: 'var(--text-secondary)',
    label: status,
  };
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '0.15rem 0.6rem',
        borderRadius: '9999px',
        fontSize: '0.75rem',
        fontWeight: 600,
        background: style.background,
        color: style.color,
        whiteSpace: 'nowrap',
      }}
    >
      {style.label}
    </span>
  );
}

const AUDIT_DAY_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
  { value: 365, label: 'Last year' },
  { value: 3650, label: 'All time' },
];

export default function AdminAISettingsPage() {
  const [models, setModels] = useState<AIModelInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // LLM gateway state
  const [policy, setPolicy] = useState<LlmAdminPolicy | null>(null);
  const [connectors, setConnectors] = useState<LlmAdminConnector[]>([]);
  const [usage, setUsage] = useState<LlmAdminUsage | null>(null);
  const [policyMessage, setPolicyMessage] = useState('');

  // Connectors-table sort state (issue #346)
  // Default-sort by health-check-recency so an admin scanning the table sees
  // the most-recently-verified rows up top — easiest first-pass triage.
  const [connectorSort, setConnectorSort] = useState<{
    key: ConnectorSortKey;
    direction: 'asc' | 'desc';
  }>({ key: 'last_health_check_at', direction: 'desc' });

  // Audit trail state (issue #341)
  const [audit, setAudit] = useState<LlmAdminAudit | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState('');
  const [auditEventType, setAuditEventType] = useState('');
  const [auditActorId, setAuditActorId] = useState('');
  const [auditConnectorId, setAuditConnectorId] = useState('');
  const [auditDays, setAuditDays] = useState(30);
  const [auditPage, setAuditPage] = useState(0);
  const [exporting, setExporting] = useState(false);

  const buildAuditFilters = useCallback(
    (overrides: Partial<AdminLlmAuditFilters> = {}): AdminLlmAuditFilters => {
      const filters: AdminLlmAuditFilters = {
        days: auditDays,
        limit: AUDIT_PAGE_SIZE,
        offset: auditPage * AUDIT_PAGE_SIZE,
      };
      if (auditEventType) filters.event_type = auditEventType;
      const actorId = parseInt(auditActorId, 10);
      if (auditActorId && !Number.isNaN(actorId)) filters.actor_user_id = actorId;
      const connectorId = parseInt(auditConnectorId, 10);
      if (auditConnectorId && !Number.isNaN(connectorId)) {
        filters.target_connector_id = connectorId;
      }
      return { ...filters, ...overrides };
    },
    [auditDays, auditPage, auditEventType, auditActorId, auditConnectorId],
  );

  const { data: settings, loading, error: loadError, setData: setSettings } = useAdminPage<AISettings>({
    pageId: PAGE_ID,
    loader: async () => {
      const [settingsData, modelsData] = await Promise.all([
        api.getAISettings(),
        api.getAIModels(),
      ]);
      setModels(modelsData.models);
      return settingsData;
    },
    onError: () => 'Failed to load AI settings',
  });

  useEffect(() => {
    let active = true;
    // Load each gateway section independently — a transient failure in one
    // request shouldn't hide the others (e.g. usage 500 should not blank the
    // policy + connectors panes).
    Promise.allSettled([
      api.getAdminLlmPolicy(),
      api.listAllLlmConnectors(),
      api.getAdminLlmUsage(30),
    ]).then(([p, c, u]) => {
      if (!active) return;
      if (p.status === 'fulfilled') setPolicy(p.value);
      if (c.status === 'fulfilled') setConnectors(c.value);
      if (u.status === 'fulfilled') setUsage(u.value);
      if (
        p.status === 'rejected' ||
        c.status === 'rejected' ||
        u.status === 'rejected'
      ) {
        setPolicyMessage('Some LLM gateway data failed to load');
      }
    });
    return () => {
      active = false;
    };
  }, []);

  // Load audit events whenever filters or the page change.
  useEffect(() => {
    let active = true;
    setAuditLoading(true);
    setAuditError('');
    api
      .getAdminLlmAudit(buildAuditFilters())
      .then((data) => {
        if (active) setAudit(data);
      })
      .catch((err) => {
        if (active) {
          setAuditError(err instanceof Error ? err.message : 'Failed to load audit events');
        }
      })
      .finally(() => {
        if (active) setAuditLoading(false);
      });
    return () => {
      active = false;
    };
  }, [buildAuditFilters]);

  const handleExportCsv = async () => {
    setExporting(true);
    setAuditError('');
    try {
      const blob = await api.downloadAdminLlmAuditCsv(buildAuditFilters());
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'llm-audit-events.csv';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setAuditError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  };

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setError('');
    setSuccess('');
    try {
      const updated = await api.updateAISettings({
        llm_enabled: settings.llm_enabled,
        llm_model: settings.llm_model,
        llm_rate_limit_per_minute: settings.llm_rate_limit_per_minute,
      });
      setSettings(updated);
      setSuccess('Settings saved');
      setTimeout(() => setSuccess(''), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handlePolicyPatch = async (next: Partial<LlmAdminPolicy>) => {
    if (!policy) return;
    setPolicyMessage('');
    const optimistic = { ...policy, ...next };
    const prev = policy;
    setPolicy(optimistic);
    try {
      const updated = await api.updateAdminLlmPolicy({
        llm_apikey_connectors_enabled: optimistic.llm_apikey_connectors_enabled,
        llm_compatible_connector_enabled: optimistic.llm_compatible_connector_enabled,
        llm_default_connector_id: optimistic.llm_default_connector_id,
        clear_default: optimistic.llm_default_connector_id === null,
        llm_call_log_retention_days: optimistic.llm_call_log_retention_days,
      });
      setPolicy(updated);
      setPolicyMessage('Policy saved');
      setTimeout(() => setPolicyMessage(''), 2000);
    } catch (err) {
      setPolicy(prev);
      setPolicyMessage(err instanceof Error ? err.message : 'Save failed');
    }
  };

  const handleRevoke = async (id: number) => {
    if (!window.confirm('Force-revoke this connector? The DJ will need to re-add it.')) return;
    try {
      const updated = await api.revokeAdminLlmConnector(id);
      setConnectors((prev) => prev.map((c) => (c.id === id ? updated : c)));
      // Reload policy in case the default changed
      const newPolicy = await api.getAdminLlmPolicy();
      setPolicy(newPolicy);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Revoke failed');
    }
  };

  if (loading) {
    return (
      <div className="container">
        <div className="loading">Loading AI settings...</div>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="container">
        <div className="card" style={{ color: 'var(--color-danger)' }}>{error || loadError || 'Failed to load'}</div>
      </div>
    );
  }

  return (
    <div className="container">
      <HelpButton page={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />
      <h1 style={{ marginBottom: '2rem' }}>AI / LLM Settings</h1>

      {(error || loadError) && (
        <div style={{ color: 'var(--color-danger)', marginBottom: '1rem' }}>{error || loadError}</div>
      )}
      {success && (
        <div style={{ color: 'var(--color-success)', marginBottom: '1rem' }}>{success}</div>
      )}

      <div className="card">
        {/* API Key Status */}
        <HelpSpot spotId="admin-ai-key" page={PAGE_ID} order={1} title="API Key Status" description="Whether an Anthropic API key is configured. Required for AI features.">
          <div className="form-group">
            <label style={{ fontWeight: 500 }}>API Key Status</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginTop: '0.25rem' }}>
              <span
                style={{
                  display: 'inline-block',
                  padding: '0.25rem 0.75rem',
                  borderRadius: '9999px',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  background: settings.api_key_configured ? 'var(--color-success-subtle)' : 'var(--color-danger-subtle)',
                  color: settings.api_key_configured ? 'var(--color-success)' : 'var(--color-danger)',
                }}
              >
                {settings.api_key_configured ? 'Configured' : 'Not Configured'}
              </span>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                {settings.api_key_masked}
              </span>
            </div>
            {!settings.api_key_configured && (
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '0.5rem' }}>
                Set ANTHROPIC_API_KEY in your environment to enable AI features.
              </p>
            )}
          </div>
        </HelpSpot>

        {/* LLM Enable/Disable */}
        <HelpSpot spotId="admin-ai-enable" page={PAGE_ID} order={2} title="Enable AI" description="Toggle AI-powered song recommendations for DJs.">
          <div className="form-group" style={{ marginTop: '1.5rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={settings.llm_enabled}
                onChange={(e) => setSettings({ ...settings, llm_enabled: e.target.checked })}
                style={{ width: '1.25rem', height: '1.25rem' }}
              />
              <div>
                <div style={{ fontWeight: 500 }}>Enable AI Recommendations</div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  When enabled, DJs can use AI Assist to get intelligent song suggestions.
                </div>
              </div>
            </label>
          </div>
        </HelpSpot>

        {/* Model Selection */}
        <HelpSpot spotId="admin-ai-model" page={PAGE_ID} order={3} title="Model Selection" description="Choose which Claude model powers recommendations.">
          <div className="form-group" style={{ marginTop: '1.5rem' }}>
            <label htmlFor="ai-model">Model</label>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              Select which Claude model to use for recommendations.
            </div>
            <select
              id="ai-model"
              className="input"
              style={{ maxWidth: '400px' }}
              value={settings.llm_model}
              onChange={(e) => setSettings({ ...settings, llm_model: e.target.value })}
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
              {/* Include current model if not in list */}
              {!models.some((m) => m.id === settings.llm_model) && (
                <option value={settings.llm_model}>{settings.llm_model}</option>
              )}
            </select>
          </div>
        </HelpSpot>

        {/* Rate Limit */}
        <HelpSpot spotId="admin-ai-rate" page={PAGE_ID} order={4} title="Rate Limit" description="Cap AI requests per DJ per minute to control costs.">
          <div className="form-group" style={{ marginTop: '1.5rem' }}>
            <label htmlFor="ai-rate-limit">Rate Limit (requests per minute per DJ)</label>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              Controls how many AI recommendation requests each DJ can make per minute. Range: 1-30.
            </div>
            <input
              id="ai-rate-limit"
              type="number"
              className="input"
              style={{ maxWidth: '200px' }}
              min={1}
              max={30}
              value={settings.llm_rate_limit_per_minute}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  llm_rate_limit_per_minute: parseInt(e.target.value) || 1,
                })
              }
            />
          </div>
        </HelpSpot>

        <button
          className="btn btn-primary"
          style={{ marginTop: '1.5rem' }}
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>

      {/* ====== LLM Gateway connector policy ====== */}
      {policy && (
        <div className="card" style={{ marginTop: '2rem' }}>
          <h2 style={{ marginTop: 0 }}>Connector policy</h2>
          {policyMessage && (
            <div style={{ marginBottom: '1rem', color: 'var(--text-secondary)' }}>{policyMessage}</div>
          )}
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={policy.llm_apikey_connectors_enabled}
              onChange={(e) => handlePolicyPatch({ llm_apikey_connectors_enabled: e.target.checked })}
            />
            Allow API-key connectors (e.g. OpenAI, Anthropic, OpenRouter, xAI, Gemini, Bedrock)
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', cursor: 'pointer', marginTop: '0.75rem' }}>
            <input
              type="checkbox"
              checked={policy.llm_compatible_connector_enabled}
              onChange={(e) => handlePolicyPatch({ llm_compatible_connector_enabled: e.target.checked })}
            />
            Allow custom OpenAI-compatible endpoints
          </label>

          <div className="form-group" style={{ marginTop: '1.5rem' }}>
            <label htmlFor="default-connector">Org default connector</label>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              Used when a system call has no DJ actor (background jobs).
            </div>
            <select
              id="default-connector"
              className="input"
              value={policy.llm_default_connector_id ?? ''}
              onChange={(e) => {
                const v = e.target.value;
                if (!v) {
                  handlePolicyPatch({ llm_default_connector_id: null });
                } else {
                  handlePolicyPatch({ llm_default_connector_id: parseInt(v) });
                }
              }}
              style={{ maxWidth: '480px' }}
            >
              <option value="">— None —</option>
              {connectors
                .filter((c) => c.status === 'active')
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.dj_username} — {c.display_name} ({TYPE_LABELS[c.connector_type] ?? c.connector_type})
                  </option>
                ))}
            </select>
          </div>

          <div className="form-group" style={{ marginTop: '1.5rem' }}>
            <label htmlFor="call-log-retention">Call log retention (days)</label>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              How long per-call telemetry (counts only, never prompt content) is kept before
              the daily cleanup deletes it. Range: 7–365 days. Changes take effect within 24 hours.
            </div>
            <input
              id="call-log-retention"
              type="number"
              className="input"
              style={{ maxWidth: '200px' }}
              min={7}
              max={365}
              value={policy.llm_call_log_retention_days}
              onChange={(e) =>
                setPolicy({
                  ...policy,
                  llm_call_log_retention_days: parseInt(e.target.value, 10) || policy.llm_call_log_retention_days,
                })
              }
              onBlur={(e) => {
                const raw = parseInt(e.target.value, 10);
                const clamped = Number.isNaN(raw)
                  ? policy.llm_call_log_retention_days
                  : Math.min(365, Math.max(7, raw));
                handlePolicyPatch({ llm_call_log_retention_days: clamped });
              }}
            />
          </div>

          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '1rem' }}>
            WrzDJ stores provider credentials encrypted at rest. Calls consume the DJ&apos;s
            quota or billing directly. Credentials are never shared between DJs.
          </p>
        </div>
      )}

      {/* ====== Per-DJ connectors table ====== */}
      <div className="card" style={{ marginTop: '2rem' }}>
        <h2 style={{ marginTop: 0 }}>Per-DJ connectors</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 0 }}>
          Background monitor verifies each connector every {' '}
          <code>LLM_HEALTH_CHECK_INTERVAL_HOURS</code> hours (default 6). DJ-triggered
          tests update the same columns.
        </p>
        {connectors.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)' }}>No DJs have connected an LLM yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <SortableHeader
                    label="DJ"
                    sortKey="dj_username"
                    activeKey={connectorSort.key}
                    direction={connectorSort.direction}
                    onSort={(k, d) => setConnectorSort({ key: k, direction: d })}
                  />
                  <PlainHeader label="Type" />
                  <PlainHeader label="Name" />
                  <PlainHeader label="Status" />
                  <SortableHeader
                    label="Last used"
                    sortKey="last_used_at"
                    activeKey={connectorSort.key}
                    direction={connectorSort.direction}
                    onSort={(k, d) => setConnectorSort({ key: k, direction: d })}
                  />
                  <SortableHeader
                    label="Last health check"
                    sortKey="last_health_check_at"
                    activeKey={connectorSort.key}
                    direction={connectorSort.direction}
                    onSort={(k, d) => setConnectorSort({ key: k, direction: d })}
                  />
                  <PlainHeader label="Result" />
                  <PlainHeader label="Actions" />
                </tr>
              </thead>
              <tbody>
                {sortConnectors(connectors, connectorSort).map((c) => (
                  <tr key={c.id}>
                    <td style={{ padding: '0.5rem' }}>{c.dj_username}</td>
                    <td style={{ padding: '0.5rem' }}>
                      {TYPE_LABELS[c.connector_type] ?? c.connector_type}
                    </td>
                    <td style={{ padding: '0.5rem' }}>{c.display_name}</td>
                    <td style={{ padding: '0.5rem' }}>{c.status}</td>
                    <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>
                      {c.last_used_at ? new Date(c.last_used_at).toLocaleString() : '—'}
                    </td>
                    <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>
                      {c.last_health_check_at
                        ? new Date(c.last_health_check_at).toLocaleString()
                        : '—'}
                    </td>
                    <td style={{ padding: '0.5rem' }}>
                      <HealthBadge status={c.last_health_check_status ?? null} />
                    </td>
                    <td style={{ padding: '0.5rem' }}>
                      {c.status !== 'disabled' && (
                        <button className="btn btn-danger" onClick={() => handleRevoke(c.id)}>
                          Force-revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ====== Usage ====== */}
      {usage && (
        <div className="card" style={{ marginTop: '2rem' }}>
          <h2 style={{ marginTop: 0 }}>Usage — last {usage.days} days</h2>
          {usage.rows.length === 0 ? (
            <p style={{ color: 'var(--text-secondary)' }}>No calls yet.</p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    {['DJ', 'Connector', 'Calls', 'Tokens in', 'Tokens out', 'Error rate'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', padding: '0.5rem', borderBottom: '1px solid var(--border-color)' }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {usage.rows.map((r) => (
                    <tr key={r.connector_id}>
                      <td style={{ padding: '0.5rem' }}>{r.dj_username}</td>
                      <td style={{ padding: '0.5rem' }}>
                        {r.display_name} <span style={{ color: 'var(--text-secondary)' }}>· {TYPE_LABELS[r.connector_type] ?? r.connector_type}</span>
                      </td>
                      <td style={{ padding: '0.5rem' }}>{r.total_calls}</td>
                      <td style={{ padding: '0.5rem' }}>{r.total_tokens_in}</td>
                      <td style={{ padding: '0.5rem' }}>{r.total_tokens_out}</td>
                      <td style={{ padding: '0.5rem' }}>{(r.error_rate * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ====== Audit trail (issue #341) ====== */}
      <div className="card" style={{ marginTop: '2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <h2 style={{ marginTop: 0, marginBottom: 0 }}>Audit trail</h2>
          <button
            className="btn"
            onClick={handleExportCsv}
            disabled={exporting}
          >
            {exporting ? 'Exporting…' : 'Export CSV'}
          </button>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: '0.5rem' }}>
          Credential lifecycle events for every connector. Export honors the active filters.
        </p>

        {/* Filters */}
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '1rem' }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="audit-event-type">Event type</label>
            <select
              id="audit-event-type"
              className="input"
              value={auditEventType}
              onChange={(e) => {
                setAuditPage(0);
                setAuditEventType(e.target.value);
              }}
            >
              <option value="">All event types</option>
              {AUDIT_EVENT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="audit-actor">Actor user ID</label>
            <input
              id="audit-actor"
              type="number"
              min={1}
              className="input"
              style={{ maxWidth: '160px' }}
              placeholder="Any"
              value={auditActorId}
              onChange={(e) => {
                setAuditPage(0);
                setAuditActorId(e.target.value);
              }}
            />
          </div>

          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="audit-connector">Connector</label>
            <select
              id="audit-connector"
              className="input"
              value={auditConnectorId}
              onChange={(e) => {
                setAuditPage(0);
                setAuditConnectorId(e.target.value);
              }}
            >
              <option value="">All connectors</option>
              {connectors.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.dj_username} — {c.display_name}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group" style={{ margin: 0 }}>
            <label htmlFor="audit-days">Date range</label>
            <select
              id="audit-days"
              className="input"
              value={auditDays}
              onChange={(e) => {
                setAuditPage(0);
                setAuditDays(parseInt(e.target.value, 10));
              }}
            >
              {AUDIT_DAY_OPTIONS.map((d) => (
                <option key={d.value} value={d.value}>{d.label}</option>
              ))}
            </select>
          </div>
        </div>

        {auditError && (
          <div style={{ color: 'var(--color-danger)', marginTop: '1rem' }}>{auditError}</div>
        )}

        {auditLoading && !audit ? (
          <p style={{ color: 'var(--text-secondary)', marginTop: '1rem' }}>Loading audit events…</p>
        ) : audit && audit.rows.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)', marginTop: '1rem' }}>No audit events match these filters.</p>
        ) : audit ? (
          <>
            <div style={{ overflowX: 'auto', marginTop: '1rem' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    {['Timestamp', 'Actor', 'Event type', 'Connector', 'Notes'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', padding: '0.5rem', borderBottom: '1px solid var(--border-color)' }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {audit.rows.map((row) => (
                    <tr key={row.id}>
                      <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>
                        {new Date(row.created_at).toLocaleString()}
                      </td>
                      <td style={{ padding: '0.5rem' }}>{row.actor_username}</td>
                      <td style={{ padding: '0.5rem' }}>{row.event_type}</td>
                      <td style={{ padding: '0.5rem' }}>
                        {row.target_connector_display_name ?? '—'}
                      </td>
                      <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>
                        {row.notes ?? '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginTop: '1rem' }}>
              <button
                className="btn"
                disabled={auditPage === 0 || auditLoading}
                onClick={() => setAuditPage((p) => Math.max(0, p - 1))}
              >
                Previous
              </button>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                {audit.total === 0
                  ? '0 events'
                  : `${audit.offset + 1}–${Math.min(audit.offset + audit.rows.length, audit.total)} of ${audit.total}`}
              </span>
              <button
                className="btn"
                disabled={auditLoading || audit.offset + AUDIT_PAGE_SIZE >= audit.total}
                onClick={() => setAuditPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
