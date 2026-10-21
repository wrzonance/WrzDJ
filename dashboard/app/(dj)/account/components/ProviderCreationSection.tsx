'use client';

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { AIModelInfo, LlmConnector, LlmConnectorCreate, LlmConnectorType } from '@/lib/api/types';
import { ProviderConfigurationFields } from './ProviderConfigurationFields';
import type { ProviderFormField, ProviderFormState } from './provider-creation-types';

export const CONNECTOR_TYPE_LABELS: Record<LlmConnectorType, string> = {
  openai_apikey: 'OpenAI API key', anthropic_apikey: 'Anthropic API key',
  openrouter_apikey: 'OpenRouter API key', xai_apikey: 'xAI Grok API key',
  gemini_apikey: 'Google Gemini API key', openai_compatible: 'Custom OpenAI-compatible endpoint',
  bedrock: 'AWS Bedrock', azure_openai: 'Azure OpenAI',
};
const EMPTY_FORM: ProviderFormState = {
  open: false, connector_type: 'openai_apikey', display_name: '', api_key: '', base_url: '',
  bearer: '', model_hint: '', aws_access_key_id: '', aws_secret_access_key: '', aws_region: '',
  aws_model_id: '', azure_resource_name: '', azure_deployment_name: '', azure_api_version: '',
};

export function ProviderCreationSection({ allowedTypes, loading, onCreated }: {
  allowedTypes: LlmConnectorType[];
  loading: boolean;
  onCreated: (connector: LlmConnector) => void;
}) {
  const [form, setForm] = useState<ProviderFormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [models, setModels] = useState<AIModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState(false);
  const [modelLoadAttempt, setModelLoadAttempt] = useState(0);
  const modelsLoadedRef = useRef(false);
  const wantsModels = form.open && form.connector_type === 'openrouter_apikey';

  useEffect(() => {
    if (!wantsModels || modelsLoadedRef.current) return;
    let active = true;
    setModelsLoading(true);
    setModelsError(false);
    api
      .listOpenRouterModels()
      .then((result) => {
        if (!active) return;
        modelsLoadedRef.current = true;
        setModels(result.models);
      })
      .catch(() => {
        if (active) setModelsError(true);
      })
      .finally(() => {
        if (active) setModelsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [wantsModels, modelLoadAttempt]);

  const updateField = (key: ProviderFormField, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));
  const openForm = () => {
    if (allowedTypes.length === 0) {
      setError('Connector creation is currently disabled by admin policy.');
      setMessage('');
      return;
    }
    setForm({ ...EMPTY_FORM, open: true, connector_type: allowedTypes[0] });
    setMessage('');
    setError('');
  };
  const cancel = () => { setForm(EMPTY_FORM); setError(''); };
  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setMessage('');
    setError('');
    const compatible = form.connector_type === 'openai_compatible';
    const bedrock = form.connector_type === 'bedrock';
    const azure = form.connector_type === 'azure_openai';
    const apiKeyProvider = !compatible && !bedrock;
    const payload: LlmConnectorCreate = {
      connector_type: form.connector_type,
      display_name: form.display_name,
      model_hint: bedrock ? null : form.model_hint || null,
      api_key: apiKeyProvider ? form.api_key : null,
      base_url: compatible ? form.base_url : null,
      bearer: compatible ? form.bearer || null : null,
      aws_access_key_id: bedrock ? form.aws_access_key_id : null,
      aws_secret_access_key: bedrock ? form.aws_secret_access_key : null,
      aws_region: bedrock ? form.aws_region : null,
      aws_model_id: bedrock ? form.aws_model_id : null,
      azure_resource_name: azure ? form.azure_resource_name : null,
      azure_deployment_name: azure ? form.azure_deployment_name : null,
      azure_api_version: azure ? form.azure_api_version : null,
    };
    try {
      const created = await api.createLlmConnector(payload);
      onCreated(created);
      setForm(EMPTY_FORM);
      setMessage(`Created "${created.display_name}". Run "Test" to verify it works.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Create failed (check your inputs)');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      {message && <div style={{ color: 'var(--color-success)', marginTop: '1rem' }}>{message}</div>}
      {error && <div style={{ color: 'var(--color-danger)', marginTop: '1rem' }}>{error}</div>}
      <section style={{ marginTop: '2rem' }}>
        {allowedTypes.length === 0 && !form.open && !loading && (
          <p style={{ color: 'var(--text-secondary)' }}>
            Connector creation is currently disabled by admin policy.
          </p>
        )}
        {allowedTypes.length > 0 && !form.open && (
          <button className="btn btn-primary" onClick={openForm}>
            + Add provider
          </button>
        )}
        {form.open && (
          <form className="card" onSubmit={create} style={{ marginTop: '1rem' }}>
            <h3 style={{ marginTop: 0 }}>Add provider</h3>

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
                onChange={(event) => updateField('display_name', event.target.value)}
                placeholder="e.g. My OpenAI"
                maxLength={80}
                required
              />
            </div>

            <ProviderConfigurationFields
              form={form}
              models={models}
              onFieldChange={updateField}
            />
            {wantsModels && modelsLoading && (
              <p role="status" style={{ color: 'var(--text-secondary)' }}>
                Loading OpenRouter models…
              </p>
            )}
            {wantsModels && modelsError && (
              <div role="alert" style={{ color: 'var(--color-danger)' }}>
                <p>OpenRouter model list could not be loaded. Enter a model manually or retry.</p>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setModelLoadAttempt((attempt) => attempt + 1)}
                >
                  Retry
                </button>
              </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
              <button type="submit" className="btn btn-primary" disabled={submitting}>
                {submitting ? 'Saving…' : 'Save'}
              </button>
              <button type="button" className="btn btn-secondary" onClick={cancel}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </section>
    </>
  );
}
