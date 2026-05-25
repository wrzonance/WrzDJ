'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { api } from '@/lib/api';
import type {
  LlmAdminPolicy,
  LlmConnector,
  LlmConnectorCreate,
  LlmConnectorType,
} from '@/lib/api-types';
import { useAuth } from '@/lib/auth';

const CONNECTOR_TYPE_LABELS: Record<LlmConnectorType, string> = {
  openai_apikey: 'OpenAI API key',
  anthropic_apikey: 'Anthropic API key',
  xai_apikey: 'xAI Grok API key',
  openai_compatible: 'Custom OpenAI-compatible endpoint',
};

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  active: { text: 'Active', color: 'var(--color-success)' },
  auth_invalid: { text: 'Auth invalid', color: 'var(--color-danger)' },
  disabled: { text: 'Disabled', color: 'var(--text-secondary)' },
};

interface FormState {
  open: boolean;
  connector_type: LlmConnectorType;
  display_name: string;
  api_key: string;
  base_url: string;
  bearer: string;
  model_hint: string;
}

const EMPTY_FORM: FormState = {
  open: false,
  connector_type: 'openai_apikey',
  display_name: '',
  api_key: '',
  base_url: '',
  bearer: '',
  model_hint: '',
};

export default function SettingsAIPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  const [policy, setPolicy] = useState<LlmAdminPolicy | null>(null);
  const [connectors, setConnectors] = useState<LlmConnector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [testStateById, setTestStateById] = useState<Record<number, string>>({});

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, isLoading, router]);

  useEffect(() => {
    let active = true;
    if (!isAuthenticated) return;
    setLoading(true);
    setError('');
    Promise.all([api.listLlmConnectors(), fetchPolicySoft()])
      .then(([rows, p]) => {
        if (!active) return;
        setConnectors(rows);
        setPolicy(p);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : 'Failed to load');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isAuthenticated]);

  const allowedTypes = useMemo(() => {
    if (!policy) return Object.keys(CONNECTOR_TYPE_LABELS) as LlmConnectorType[];
    const out: LlmConnectorType[] = [];
    if (policy.llm_apikey_connectors_enabled) {
      out.push('openai_apikey', 'anthropic_apikey', 'xai_apikey');
    }
    if (policy.llm_compatible_connector_enabled) out.push('openai_compatible');
    return out;
  }, [policy]);

  if (isLoading || !isAuthenticated) return null;

  const handleOpenForm = () => {
    if (allowedTypes.length === 0) {
      setSubmitError('Connector creation is currently disabled by admin policy.');
      setSubmitMessage('');
      return;
    }
    setForm({ ...EMPTY_FORM, open: true, connector_type: allowedTypes[0] });
    setSubmitMessage('');
    setSubmitError('');
  };

  const handleCancel = () => {
    setForm(EMPTY_FORM);
    setSubmitError('');
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setSubmitMessage('');
    setSubmitError('');
    const payload: LlmConnectorCreate = {
      connector_type: form.connector_type,
      display_name: form.display_name,
      model_hint: form.model_hint || null,
      api_key:
        form.connector_type === 'openai_compatible' ? null : form.api_key,
      base_url:
        form.connector_type === 'openai_compatible' ? form.base_url : null,
      bearer:
        form.connector_type === 'openai_compatible' ? form.bearer || null : null,
    };
    try {
      const created = await api.createLlmConnector(payload);
      setConnectors((prev) => [created, ...prev]);
      setForm(EMPTY_FORM);
      setSubmitMessage(`Created "${created.display_name}". Run "Test" to verify it works.`);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : 'Create failed (check your inputs)',
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleTest = async (id: number) => {
    setTestStateById((s) => ({ ...s, [id]: 'Testing…' }));
    try {
      const result = await api.testLlmConnector(id);
      setTestStateById((s) => ({
        ...s,
        [id]: result.ok ? 'OK' : `Failed: ${result.error_code ?? 'unknown'}`,
      }));
      // Refresh the row so updated status renders
      const fresh = await api.listLlmConnectors();
      setConnectors(fresh);
    } catch (err) {
      setTestStateById((s) => ({
        ...s,
        [id]: err instanceof Error ? err.message : 'Test failed',
      }));
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this connector? This cannot be undone.')) return;
    try {
      await api.deleteLlmConnector(id);
      setConnectors((prev) => prev.filter((c) => c.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  return (
    <main style={{ maxWidth: '720px', margin: '0 auto', padding: '2rem 1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        <Link href="/dashboard" style={{ color: 'var(--text-secondary)', textDecoration: 'none', fontSize: '0.875rem' }}>
          ← Dashboard
        </Link>
        <h1 style={{ margin: 0 }}>AI providers</h1>
      </div>

      <p style={{ color: 'var(--text-secondary)' }}>
        Connect your own LLM provider so AI-assisted features (recommendations, etc.) bill to
        your account. Credentials are encrypted at rest. Calls consume your account&apos;s API or
        subscription quota directly.
      </p>

      {loading && <div className="loading">Loading…</div>}
      {error && <div style={{ color: 'var(--color-danger)', marginTop: '1rem' }}>{error}</div>}
      {submitMessage && (
        <div style={{ color: 'var(--color-success)', marginTop: '1rem' }}>{submitMessage}</div>
      )}
      {submitError && (
        <div style={{ color: 'var(--color-danger)', marginTop: '1rem' }}>{submitError}</div>
      )}

      <section style={{ marginTop: '2rem' }}>
        <h2>Connected providers</h2>
        {connectors.length === 0 && !loading && (
          <p style={{ color: 'var(--text-secondary)' }}>No connectors yet.</p>
        )}
        {connectors.map((c) => {
          const status = STATUS_LABELS[c.status] ?? { text: c.status, color: 'var(--text-secondary)' };
          return (
            <div key={c.id} className="card" style={{ marginTop: '1rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{c.display_name}</div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                    {CONNECTOR_TYPE_LABELS[c.connector_type as LlmConnectorType] ?? c.connector_type}
                    {c.model_hint ? ` · ${c.model_hint}` : ''}
                    {c.base_url_plain ? ` · ${c.base_url_plain}` : ''}
                  </div>
                  <div style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: status.color, fontWeight: 600 }}>
                    {status.text}
                    {testStateById[c.id] ? ` · ${testStateById[c.id]}` : ''}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <button className="btn btn-secondary" onClick={() => handleTest(c.id)}>
                    Test
                  </button>
                  <button className="btn btn-danger" onClick={() => handleDelete(c.id)}>
                    Delete
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </section>

      <section style={{ marginTop: '2rem' }}>
        {allowedTypes.length === 0 && !form.open && (
          <p style={{ color: 'var(--text-secondary)' }}>
            Connector creation is currently disabled by admin policy.
          </p>
        )}
        {allowedTypes.length > 0 && !form.open && (
          <button className="btn btn-primary" onClick={handleOpenForm}>
            + Add provider
          </button>
        )}
        {form.open && (
          <form className="card" onSubmit={handleCreate} style={{ marginTop: '1rem' }}>
            <h2 style={{ marginTop: 0 }}>Add provider</h2>

            <div className="form-group">
              <label htmlFor="connector_type">Provider</label>
              <select
                id="connector_type"
                className="input"
                value={form.connector_type}
                onChange={(e) =>
                  setForm({ ...form, connector_type: e.target.value as LlmConnectorType })
                }
              >
                {allowedTypes.map((t) => (
                  <option key={t} value={t}>
                    {CONNECTOR_TYPE_LABELS[t]}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="display_name">Display name</label>
              <input
                id="display_name"
                className="input"
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                placeholder="e.g. My OpenAI"
                maxLength={80}
                required
              />
            </div>

            {form.connector_type !== 'openai_compatible' ? (
              <div className="form-group">
                <label htmlFor="api_key">API key</label>
                <input
                  id="api_key"
                  className="input"
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  placeholder={
                    form.connector_type === 'anthropic_apikey'
                      ? 'sk-ant-…'
                      : form.connector_type === 'xai_apikey'
                      ? 'xai-…'
                      : 'sk-proj-… / sk-…'
                  }
                  required
                />
              </div>
            ) : (
              <>
                <div className="form-group">
                  <label htmlFor="base_url">Base URL</label>
                  <input
                    id="base_url"
                    className="input"
                    value={form.base_url}
                    onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                    placeholder="http://127.0.0.1:11434/v1"
                    required
                  />
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.5rem 0 0' }}>
                    HTTPS is required for public hosts. HTTP is only allowed for loopback (
                    <code>127.0.0.1</code>, <code>localhost</code>) and private (RFC1918) IPs.
                  </p>
                </div>
                <div className="form-group">
                  <label htmlFor="bearer">Bearer token (optional)</label>
                  <input
                    id="bearer"
                    className="input"
                    type="password"
                    value={form.bearer}
                    onChange={(e) => setForm({ ...form, bearer: e.target.value })}
                  />
                </div>
                <details style={{ marginTop: '1rem' }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
                    Want to use your ChatGPT Plus / Pro subscription?
                  </summary>
                  <p style={{ marginTop: '0.5rem' }}>
                    Install{' '}
                    <a
                      href="https://github.com/NousResearch/hermes-agent"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Hermes Agent
                    </a>
                    , run <code>hermes proxy</code>, and paste the URL it prints below. Your
                    ChatGPT account never leaves your machine — WrzDJ only talks to your local
                    Hermes proxy.
                  </p>
                </details>
              </>
            )}

            <div className="form-group">
              <label htmlFor="model_hint">Model (optional)</label>
              <input
                id="model_hint"
                className="input"
                value={form.model_hint}
                onChange={(e) => setForm({ ...form, model_hint: e.target.value })}
                placeholder={
                  form.connector_type === 'anthropic_apikey'
                    ? 'claude-haiku-4-5-20251001'
                    : form.connector_type === 'openai_apikey'
                    ? 'gpt-5-mini'
                    : form.connector_type === 'xai_apikey'
                    ? 'grok-3-mini'
                    : 'e.g. llama3'
                }
              />
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
              <button type="submit" className="btn btn-primary" disabled={submitting}>
                {submitting ? 'Saving…' : 'Save'}
              </button>
              <button type="button" className="btn btn-secondary" onClick={handleCancel}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </section>
    </main>
  );
}

async function fetchPolicySoft(): Promise<LlmAdminPolicy | null> {
  // DJ users don't have access to the admin policy endpoint — return null so
  // the UI falls back to "all types allowed" defaults. Admins get the real
  // payload (the same component is used in the admin /admin/ai page).
  try {
    return await api.getAdminLlmPolicy();
  } catch {
    return null;
  }
}
