'use client';

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type {
  AISettings,
  LlmAdminConnector,
  LlmAdminPolicy,
  LlmConnector,
  LlmDjStatusRow,
} from '@/lib/api/types';
import { useAdminPage } from '@/lib/use-admin-page';
import { HelpSpot } from '@/components/help/HelpSpot';
import { PageControls } from '@/components/PageControls';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';
import { OrgConnectorSection, TYPE_LABELS } from './OrgConnectorSection';
import { AuditTrail } from './AuditTrail';
import { UsagePanel } from './UsagePanel';

const PAGE_ID = 'admin-ai';

// Effective LLM credential source per DJ — computed by the backend with the
// same rules the gateway resolver applies (see /api/admin/llm/dj-status).
const SOURCE_LABELS: Record<string, { text: string; color: string }> = {
  own: { text: 'Own connector', color: 'var(--color-success)' },
  org_fallback: { text: 'Org fallback', color: 'var(--color-warning)' },
  none: { text: 'None — AI unavailable', color: 'var(--color-danger)' },
};

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

// Format a nullable ISO timestamp for table cells; em-dash when absent.
function formatTimestamp(ts: string | null | undefined): string {
  return ts ? new Date(ts).toLocaleString() : '—';
}

// Percent of the monthly cap consumed (issue #339). Returns null when there is
// no cap (unlimited) so the UI renders no bar. Clamps to 0–100 so an over-cap
// connector (possible when a cap is lowered mid-month) shows a full bar.
function capPercent(used: number, cap: number | null | undefined): number | null {
  if (cap == null) return null;
  if (cap === 0) return 100;
  return Math.min(100, Math.max(0, Math.round((used / cap) * 100)));
}

// Bar colour escalates with consumption: green < 80% < amber < 100% red.
function capBarColor(percent: number): string {
  if (percent >= 100) return 'var(--color-danger)';
  if (percent >= 80) return 'var(--color-warning, #c08418)';
  return 'var(--color-success)';
}

function PlainHeader({ label }: { label: string }) {
  return (
    <th
      style={{ textAlign: 'left', padding: '0.5rem', borderBottom: '1px solid var(--border)' }}
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
        borderBottom: '1px solid var(--border)',
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

export default function AdminAISettingsPage() {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // LLM gateway state
  const [policy, setPolicy] = useState<LlmAdminPolicy | null>(null);
  const [connectors, setConnectors] = useState<LlmAdminConnector[]>([]);
  const [orgConnectors, setOrgConnectors] = useState<LlmConnector[]>([]);
  const [djStatus, setDjStatus] = useState<LlmDjStatusRow[]>([]);
  const [policyMessage, setPolicyMessage] = useState('');

  // Connectors-table sort state (issue #346)
  // Default-sort by health-check-recency so an admin scanning the table sees
  // the most-recently-verified rows up top — easiest first-pass triage.
  const [connectorSort, setConnectorSort] = useState<{
    key: ConnectorSortKey;
    direction: 'asc' | 'desc';
  }>({ key: 'last_health_check_at', direction: 'desc' });

  const { data: settings, loading, error: loadError, setData: setSettings } = useAdminPage<AISettings>({
    pageId: PAGE_ID,
    loader: () => api.getAISettings(),
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
      api.listOrgConnectors(),
      api.getDjLlmStatus(),
    ]).then(([p, c, o, d]) => {
      if (!active) return;
      if (p.status === 'fulfilled') setPolicy(p.value);
      if (c.status === 'fulfilled') setConnectors(c.value);
      if (o.status === 'fulfilled') setOrgConnectors(o.value);
      if (d.status === 'fulfilled') setDjStatus(d.value.rows);
      if ([p, c, o, d].some((r) => r.status === 'rejected')) {
        setPolicyMessage('Some LLM gateway data failed to load');
      }
    });
    return () => {
      active = false;
    };
  }, []);

  // Reload the org connector list + per-DJ effective sources after any org
  // connector mutation — both derive from the same scope-aware resolver. Also
  // refresh the policy: deleting the default org connector clears
  // llm_default_connector_id server-side, and handlePolicyPatch re-sends the
  // full payload, so a stale id would make every later policy edit 400.
  const reloadOrgConnectors = useCallback(async () => {
    const [o, d, p] = await Promise.allSettled([
      api.listOrgConnectors(),
      api.getDjLlmStatus(),
      api.getAdminLlmPolicy(),
    ]);
    if (o.status === 'fulfilled') setOrgConnectors(o.value);
    if (d.status === 'fulfilled') setDjStatus(d.value.rows);
    if (p.status === 'fulfilled') setPolicy(p.value);
  }, []);

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setError('');
    setSuccess('');
    try {
      const updated = await api.updateAISettings({
        llm_enabled: settings.llm_enabled,
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

  const handleCapBlur = async (connector: LlmAdminConnector, raw: string) => {
    const trimmed = raw.trim();
    // Empty input clears the cap (unlimited).
    let next: number | null;
    if (trimmed === '') {
      next = null;
    } else {
      const parsed = parseInt(trimmed, 10);
      if (Number.isNaN(parsed) || parsed < 0) {
        setError('Monthly cap must be a non-negative whole number.');
        return;
      }
      next = parsed;
    }
    // No-op when unchanged.
    if (next === (connector.monthly_token_cap ?? null)) return;
    try {
      const updated = await api.setAdminLlmConnectorCap(connector.id, next);
      setConnectors((prev) => prev.map((c) => (c.id === connector.id ? updated : c)));
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update cap');
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
        <PageControls />
        <div className="loading">Loading AI settings...</div>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="container">
        <PageControls />
        <div className="card" style={{ color: 'var(--color-danger)' }}>{error || loadError || 'Failed to load'}</div>
      </div>
    );
  }

  return (
    <div className="container">
      <PageControls helpPage={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />
      <h1 style={{ marginBottom: '2rem' }}>AI / LLM Settings</h1>

      {(error || loadError) && (
        <div style={{ color: 'var(--color-danger)', marginBottom: '1rem' }}>{error || loadError}</div>
      )}
      {success && (
        <div style={{ color: 'var(--color-success)', marginBottom: '1rem' }}>{success}</div>
      )}

      <div className="card">
        {/* Org-fallback toggle: gates ONLY whether connector-less DJs fall back
            to the org connector (house-billed). DJs with their own connectors
            are never blocked by it. */}
        <HelpSpot spotId="admin-ai-enable" page={PAGE_ID} order={1} title="Organization fallback" description="When off, only DJs who connected their own provider can use AI features. DJs' own connectors are never blocked by this switch.">
          <div className="form-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={settings.llm_enabled}
                onChange={(e) => setSettings({ ...settings, llm_enabled: e.target.checked })}
                style={{ width: '1.25rem', height: '1.25rem' }}
              />
              <div>
                <div style={{ fontWeight: 500 }}>
                  Allow DJs without their own connector to use the organization connector
                  (house-billed)
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  When off, only DJs who connected their own provider can use AI features.
                </div>
              </div>
            </label>
          </div>
        </HelpSpot>

        {/* Rate Limit */}
        <HelpSpot spotId="admin-ai-rate" page={PAGE_ID} order={2} title="Rate Limit" description="Cap AI requests per DJ per minute to control costs.">
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

      {/* ====== Organization (house) connector ====== */}
      <OrgConnectorSection connectors={orgConnectors} onChanged={reloadOrgConnectors} />

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
              Connector-less DJs and background jobs use this connector when fallback is allowed.
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
              {orgConnectors
                .filter((c) => c.status === 'active')
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    Organization — {c.display_name} ({TYPE_LABELS[c.connector_type] ?? c.connector_type})
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
            WrzDJ stores provider credentials encrypted at rest. DJ-owned connectors bill the
            DJ directly and are never shared between DJs; the organization connector bills
            the organization.
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
                  <PlainHeader label="Monthly cap" />
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
                      {formatTimestamp(c.last_used_at)}
                    </td>
                    <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>
                      {formatTimestamp(c.last_health_check_at)}
                    </td>
                    <td style={{ padding: '0.5rem' }}>
                      <HealthBadge status={c.last_health_check_status ?? null} />
                    </td>
                    <td style={{ padding: '0.5rem', minWidth: '180px' }}>
                      <input
                        type="number"
                        className="input"
                        style={{ width: '110px' }}
                        min={0}
                        placeholder="∞"
                        defaultValue={c.monthly_token_cap ?? ''}
                        onBlur={(e) => handleCapBlur(c, e.target.value)}
                        aria-label={`Monthly token cap for ${c.dj_username} ${c.display_name}`}
                      />
                      <div
                        style={{
                          marginTop: '0.35rem',
                          fontSize: '0.75rem',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {c.monthly_token_cap == null
                          ? `${c.current_month_tokens.toLocaleString()} this month · unlimited`
                          : `${c.current_month_tokens.toLocaleString()} / ${c.monthly_token_cap.toLocaleString()}`}
                      </div>
                      {c.monthly_token_cap != null && (
                        <div
                          aria-hidden
                          style={{
                            marginTop: '0.25rem',
                            height: '6px',
                            borderRadius: '9999px',
                            background: 'var(--border)',
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              width: `${capPercent(c.current_month_tokens, c.monthly_token_cap) ?? 0}%`,
                              height: '100%',
                              background: capBarColor(
                                capPercent(c.current_month_tokens, c.monthly_token_cap) ?? 0,
                              ),
                            }}
                          />
                        </div>
                      )}
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

        {/* DJ access: effective credential source per DJ (own / org fallback / none) */}
        <h3 style={{ marginTop: '1.5rem', marginBottom: '0.25rem' }}>DJ access</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 0 }}>
          Where each DJ&apos;s AI calls are billed — their own connector, the organization
          fallback, or nowhere (AI unavailable).
        </p>
        {djStatus.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)' }}>No DJs found.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {djStatus.map((row) => {
              const label = SOURCE_LABELS[row.effective_source] ?? {
                text: row.effective_source,
                color: 'var(--text-secondary)',
              };
              return (
                <div
                  key={row.user_id}
                  style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}
                >
                  <span style={{ minWidth: '160px' }}>{row.username}</span>
                  <span style={{ color: label.color, fontSize: '0.875rem', fontWeight: 600 }}>
                    {label.text}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <UsagePanel />
      <AuditTrail connectors={connectors} />
    </div>
  );
}
