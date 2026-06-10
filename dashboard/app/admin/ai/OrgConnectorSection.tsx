'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import type { LlmConnector, LlmConnectorCreate } from '@/lib/api-types';

export const TYPE_LABELS: Record<string, string> = {
  openai_apikey: 'OpenAI',
  anthropic_apikey: 'Anthropic',
  openrouter_apikey: 'OpenRouter',
  xai_apikey: 'xAI',
  gemini_apikey: 'Gemini',
  openai_compatible: 'OpenAI-compatible',
  bedrock: 'AWS Bedrock',
  azure_openai: 'Azure OpenAI',
};

type OrgConnectorType = LlmConnectorCreate['connector_type'];

// API-key-only subset for the org house-connector form. Compatible / Bedrock /
// Azure connectors need extra fields (base URL, region, deployment name) that
// only the DJ-side provider form collects — admins needing those can connect
// them as a DJ; the org form keeps to simple api-key types.
const ORG_FORM_TYPES: Array<{ value: OrgConnectorType; label: string }> = [
  { value: 'openai_apikey', label: TYPE_LABELS.openai_apikey },
  { value: 'anthropic_apikey', label: TYPE_LABELS.anthropic_apikey },
  { value: 'openrouter_apikey', label: TYPE_LABELS.openrouter_apikey },
  { value: 'xai_apikey', label: TYPE_LABELS.xai_apikey },
  { value: 'gemini_apikey', label: TYPE_LABELS.gemini_apikey },
];

const STATUS_BADGES: Record<string, { background: string; color: string; label: string }> = {
  active: {
    background: 'var(--color-success-subtle)',
    color: 'var(--color-success)',
    label: 'Active',
  },
  auth_invalid: {
    background: 'var(--color-danger-subtle)',
    color: 'var(--color-danger)',
    label: 'Auth invalid',
  },
  disabled: {
    background: 'var(--color-danger-subtle)',
    color: 'var(--color-danger)',
    label: 'Disabled',
  },
};

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_BADGES[status] ?? {
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

interface OrgConnectorSectionProps {
  connectors: LlmConnector[];
  onChanged: () => Promise<void> | void;
}

export function OrgConnectorSection({ connectors, onChanged }: OrgConnectorSectionProps) {
  const [connectorType, setConnectorType] = useState<OrgConnectorType>('openai_apikey');
  const [displayName, setDisplayName] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [modelHint, setModelHint] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const handleCreate = async () => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await api.createOrgConnector({
        connector_type: connectorType,
        display_name: displayName.trim(),
        api_key: apiKey,
        model_hint: modelHint.trim() || null,
      });
      setDisplayName('');
      setApiKey('');
      setModelHint('');
      setMessage('Organization connector created');
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create connector');
    } finally {
      setBusy(false);
    }
  };

  const handleTest = async (id: number) => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const result = await api.testOrgConnector(id);
      if (result.ok) {
        setMessage(result.message ?? 'Connection OK');
      } else {
        setError(result.message ?? result.error_code ?? 'Test failed');
      }
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test failed');
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (
      !window.confirm(
        'Delete this organization connector? Connector-less DJs will lose AI access.',
      )
    ) {
      return;
    }
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await api.deleteOrgConnector(id);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginTop: '2rem' }}>
      <h2 style={{ marginTop: 0 }}>Organization connector</h2>
      <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 0 }}>
        The house credential. DJs without their own connector fall back to it when the toggle
        allows — usage is billed to the organization.
      </p>

      {error && <div style={{ color: 'var(--color-danger)', marginBottom: '1rem' }}>{error}</div>}
      {message && (
        <div style={{ color: 'var(--color-success)', marginBottom: '1rem' }}>{message}</div>
      )}

      {connectors.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1.5rem' }}>
          {connectors.map((c) => (
            <div
              key={c.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
                flexWrap: 'wrap',
                padding: '0.75rem',
                border: '1px solid var(--border-color)',
                borderRadius: '8px',
              }}
            >
              <div style={{ flex: 1, minWidth: '200px' }}>
                <div style={{ fontWeight: 500 }}>{c.display_name}</div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  {TYPE_LABELS[c.connector_type] ?? c.connector_type}
                  {c.model_hint ? ` · ${c.model_hint}` : ''}
                </div>
              </div>
              <StatusBadge status={c.status} />
              <button className="btn" onClick={() => handleTest(c.id)} disabled={busy}>
                Test
              </button>
              <button className="btn btn-danger" onClick={() => handleDelete(c.id)} disabled={busy}>
                Delete
              </button>
            </div>
          ))}
        </div>
      )}

      <h3 style={{ marginBottom: '0.5rem' }}>
        {connectors.length === 0 ? 'Add the organization connector' : 'Add another connector'}
      </h3>
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div className="form-group" style={{ margin: 0 }}>
          <label htmlFor="org-connector-type">Provider</label>
          <select
            id="org-connector-type"
            className="input"
            value={connectorType}
            onChange={(e) => setConnectorType(e.target.value as OrgConnectorType)}
          >
            {ORG_FORM_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label htmlFor="org-display-name">Display name</label>
          <input
            id="org-display-name"
            type="text"
            className="input"
            placeholder="House OpenAI"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label htmlFor="org-api-key">API key</label>
          <input
            id="org-api-key"
            type="password"
            className="input"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label htmlFor="org-model-hint">Model hint (optional)</label>
          <input
            id="org-model-hint"
            type="text"
            className="input"
            placeholder="e.g. gpt-5-mini"
            value={modelHint}
            onChange={(e) => setModelHint(e.target.value)}
          />
        </div>
        <button
          className="btn btn-primary"
          onClick={handleCreate}
          disabled={busy || !displayName.trim() || !apiKey.trim()}
        >
          Add connector
        </button>
      </div>
    </div>
  );
}
