'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { api } from '@/lib/api';
import type {
  AIModelInfo,
  LlmConnector,
  LlmConnectorCreate,
  LlmConnectorType,
  LlmDjPolicy,
} from '@/lib/api-types';
import { useAuth } from '@/lib/auth';

const CONNECTOR_TYPE_LABELS: Record<LlmConnectorType, string> = {
  openai_apikey: 'OpenAI API key',
  anthropic_apikey: 'Anthropic API key',
  openrouter_apikey: 'OpenRouter API key',
  xai_apikey: 'xAI Grok API key',
  gemini_apikey: 'Google Gemini API key',
  openai_compatible: 'Custom OpenAI-compatible endpoint',
  bedrock: 'AWS Bedrock',
  azure_openai: 'Azure OpenAI',
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
  aws_access_key_id: string;
  aws_secret_access_key: string;
  aws_region: string;
  aws_model_id: string;
  azure_resource_name: string;
  azure_deployment_name: string;
  azure_api_version: string;
}

const EMPTY_FORM: FormState = {
  open: false,
  connector_type: 'openai_apikey',
  display_name: '',
  api_key: '',
  base_url: '',
  bearer: '',
  model_hint: '',
  aws_access_key_id: '',
  aws_secret_access_key: '',
  aws_region: '',
  aws_model_id: '',
  azure_resource_name: '',
  azure_deployment_name: '',
  azure_api_version: '',
};

export default function SettingsAIPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  const [policy, setPolicy] = useState<LlmDjPolicy | null>(null);
  const [connectors, setConnectors] = useState<LlmConnector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [testStateById, setTestStateById] = useState<Record<number, string>>({});
  const [openrouterModels, setOpenrouterModels] = useState<AIModelInfo[]>([]);
  const [openrouterModelsLoaded, setOpenrouterModelsLoaded] = useState(false);

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

  // Lazily fetch the OpenRouter model catalogue the first time a DJ opens the
  // form on the OpenRouter type. Best-effort: an empty list (or a failed fetch)
  // simply falls back to the free-text model input. Fetched once per mount.
  const wantsOpenrouterModels = form.open && form.connector_type === 'openrouter_apikey';
  useEffect(() => {
    if (!wantsOpenrouterModels || openrouterModelsLoaded) return;
    setOpenrouterModelsLoaded(true);
    api
      .listOpenRouterModels()
      .then((res) => setOpenrouterModels(res.models))
      .catch(() => {
        // Swallow — the dropdown gracefully degrades to free-text entry.
      });
  }, [wantsOpenrouterModels, openrouterModelsLoaded]);

  const allowedTypes = useMemo<LlmConnectorType[]>(() => {
    // Fail closed: when the policy can't be read, offer no providers rather than
    // surfacing every type and letting the DJ pick one the admin disabled (the
    // create call would 403). The server is the source of truth for the set.
    if (!policy) return [];
    return policy.allowed_connector_types as LlmConnectorType[];
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
    const isCompatible = form.connector_type === 'openai_compatible';
    const isBedrock = form.connector_type === 'bedrock';
    const isAzure = form.connector_type === 'azure_openai';
    // API-key providers: everything that isn't openai_compatible or bedrock.
    // Azure also carries an api_key (plus its azure_* fields).
    const isApiKey = !isCompatible && !isBedrock;
    const payload: LlmConnectorCreate = {
      connector_type: form.connector_type,
      display_name: form.display_name,
      // Bedrock has no model_hint field (it uses aws_model_id); never post a
      // stale hint left over from a prior connector-type selection.
      model_hint: isBedrock ? null : form.model_hint || null,
      api_key: isApiKey ? form.api_key : null,
      base_url: isCompatible ? form.base_url : null,
      bearer: isCompatible ? form.bearer || null : null,
      aws_access_key_id: isBedrock ? form.aws_access_key_id : null,
      aws_secret_access_key: isBedrock ? form.aws_secret_access_key : null,
      aws_region: isBedrock ? form.aws_region : null,
      aws_model_id: isBedrock ? form.aws_model_id : null,
      azure_resource_name: isAzure ? form.azure_resource_name : null,
      azure_deployment_name: isAzure ? form.azure_deployment_name : null,
      azure_api_version: isAzure ? form.azure_api_version : null,
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
        {allowedTypes.length === 0 && !form.open && !loading && (
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

            {form.connector_type === 'bedrock' ? (
              <>
                <div className="form-group">
                  <label htmlFor="aws_access_key_id">AWS access key ID</label>
                  <input
                    id="aws_access_key_id"
                    className="input"
                    value={form.aws_access_key_id}
                    onChange={(e) => setForm({ ...form, aws_access_key_id: e.target.value })}
                    placeholder="AKIA…"
                    autoComplete="off"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="aws_secret_access_key">AWS secret access key</label>
                  <input
                    id="aws_secret_access_key"
                    className="input"
                    type="password"
                    value={form.aws_secret_access_key}
                    onChange={(e) => setForm({ ...form, aws_secret_access_key: e.target.value })}
                    autoComplete="off"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="aws_region">AWS region</label>
                  <input
                    id="aws_region"
                    className="input"
                    value={form.aws_region}
                    onChange={(e) => setForm({ ...form, aws_region: e.target.value })}
                    placeholder="us-east-1"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="aws_model_id">Bedrock model ID</label>
                  <input
                    id="aws_model_id"
                    className="input"
                    value={form.aws_model_id}
                    onChange={(e) => setForm({ ...form, aws_model_id: e.target.value })}
                    placeholder="anthropic.claude-3-5-sonnet-20241022-v2:0"
                    required
                  />
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.5rem 0 0' }}>
                    Calls are signed with AWS SigV4 and billed to your AWS account.
                    Claude (<code>anthropic.*</code>) and Llama (<code>meta.*</code>)
                    model families are supported.
                  </p>
                </div>
              </>
            ) : form.connector_type === 'azure_openai' ? (
              <>
                <div className="form-group">
                  <label htmlFor="api_key">API key</label>
                  <input
                    id="api_key"
                    className="input"
                    type="password"
                    value={form.api_key}
                    onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                    placeholder="Azure OpenAI key"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="azure_resource_name">Resource name</label>
                  <input
                    id="azure_resource_name"
                    className="input"
                    value={form.azure_resource_name}
                    onChange={(e) =>
                      setForm({ ...form, azure_resource_name: e.target.value })
                    }
                    placeholder="e.g. my-company"
                    required
                  />
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.5rem 0 0' }}>
                    The resource subdomain in{' '}
                    <code>https://&lt;resource&gt;.openai.azure.com</code>.
                  </p>
                </div>
                <div className="form-group">
                  <label htmlFor="azure_deployment_name">Deployment name</label>
                  <input
                    id="azure_deployment_name"
                    className="input"
                    value={form.azure_deployment_name}
                    onChange={(e) =>
                      setForm({ ...form, azure_deployment_name: e.target.value })
                    }
                    placeholder="e.g. gpt-4o-prod"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="azure_api_version">API version</label>
                  <input
                    id="azure_api_version"
                    className="input"
                    value={form.azure_api_version}
                    onChange={(e) =>
                      setForm({ ...form, azure_api_version: e.target.value })
                    }
                    placeholder="e.g. 2024-06-01"
                    required
                  />
                </div>
              </>
            ) : form.connector_type !== 'openai_compatible' ? (
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
                      : form.connector_type === 'openrouter_apikey'
                      ? 'sk-or-…'
                      : form.connector_type === 'xai_apikey'
                      ? 'xai-…'
                      : form.connector_type === 'gemini_apikey'
                      ? 'AIza…'
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

            {form.connector_type !== 'bedrock' && (
              <div className="form-group">
                <label htmlFor="model_hint">Model (optional)</label>
                {form.connector_type === 'openrouter_apikey' && openrouterModels.length > 0 ? (
                  <>
                    <select
                      id="model_hint"
                      className="input"
                      value={form.model_hint}
                      onChange={(e) => setForm({ ...form, model_hint: e.target.value })}
                    >
                      <option value="">Default (openai/gpt-4o-mini)</option>
                      {openrouterModels.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} ({m.id})
                        </option>
                      ))}
                    </select>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.5rem 0 0' }}>
                      Each model routes through OpenRouter and bills your account at that model&apos;s
                      OpenRouter rate (see openrouter.ai/models for per-token pricing).
                    </p>
                  </>
                ) : (
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
                        : form.connector_type === 'openrouter_apikey'
                        ? 'e.g. openai/gpt-4o-mini'
                        : form.connector_type === 'xai_apikey'
                        ? 'grok-3-mini'
                        : form.connector_type === 'gemini_apikey'
                        ? 'gemini-2.5-flash'
                        : 'e.g. llama3'
                    }
                  />
                )}
              </div>
            )}

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

async function fetchPolicySoft(): Promise<LlmDjPolicy | null> {
  // Read the DJ-scoped policy endpoint. On any failure we return null and the
  // UI fails *closed* (no providers offered) — see `allowedTypes`. This avoids
  // showing a DJ a provider the admin disabled, only to have the create call
  // reject it with a 403.
  try {
    return await api.getLlmPolicy();
  } catch {
    return null;
  }
}
