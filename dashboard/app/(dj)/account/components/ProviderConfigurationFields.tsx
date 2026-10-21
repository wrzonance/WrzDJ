'use client';

import type { AIModelInfo, LlmConnectorType } from '@/lib/api/types';
import type { ProviderFormField, ProviderFormState } from './provider-creation-types';

const API_KEY_PLACEHOLDERS: Partial<Record<LlmConnectorType, string>> = {
  anthropic_apikey: 'sk-ant-…', openrouter_apikey: 'sk-or-…', xai_apikey: 'xai-…', gemini_apikey: 'AIza…',
};
const MODEL_HINT_PLACEHOLDERS: Partial<Record<LlmConnectorType, string>> = {
  anthropic_apikey: 'claude-haiku-4-5-20251001', openai_apikey: 'gpt-5-mini',
  openrouter_apikey: 'e.g. openai/gpt-4o-mini', xai_apikey: 'grok-3-mini', gemini_apikey: 'gemini-2.5-flash',
};
const API_KEY_PLACEHOLDER_DEFAULT = 'sk-proj-… / sk-…';
const MODEL_HINT_PLACEHOLDER_DEFAULT = 'e.g. llama3';
const helpTextStyle = { color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.5rem 0 0' };

export function ProviderConfigurationFields({
  form,
  models,
  onFieldChange,
}: {
  form: ProviderFormState;
  models: AIModelInfo[];
  onFieldChange: (key: ProviderFormField, value: string) => void;
}) {
  const field = (key: ProviderFormField) => ({
    value: form[key],
    onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
      onFieldChange(key, event.target.value),
  });

  return (
    <>
      {form.connector_type === 'bedrock' ? (
        <>
          <div className="form-group">
            <label htmlFor="aws_access_key_id">AWS access key ID</label>
            <input id="aws_access_key_id" className="input" {...field('aws_access_key_id')} placeholder="AKIA…" autoComplete="off" required />
          </div>
          <div className="form-group">
            <label htmlFor="aws_secret_access_key">AWS secret access key</label>
            <input id="aws_secret_access_key" className="input" type="password" {...field('aws_secret_access_key')} autoComplete="off" required />
          </div>
          <div className="form-group">
            <label htmlFor="aws_region">AWS region</label>
            <input id="aws_region" className="input" {...field('aws_region')} placeholder="us-east-1" required />
          </div>
          <div className="form-group">
            <label htmlFor="aws_model_id">Bedrock model ID</label>
            <input id="aws_model_id" className="input" {...field('aws_model_id')} placeholder="anthropic.claude-3-5-sonnet-20241022-v2:0" required />
            <p style={helpTextStyle}>
              Calls are signed with AWS SigV4 and billed to your AWS account. Claude (<code>anthropic.*</code>) and Llama (<code>meta.*</code>) model families are supported.
            </p>
          </div>
        </>
      ) : form.connector_type === 'azure_openai' ? (
        <>
          <div className="form-group">
            <label htmlFor="api_key">API key</label>
            <input id="api_key" className="input" type="password" {...field('api_key')} placeholder="Azure OpenAI key" required />
          </div>
          <div className="form-group">
            <label htmlFor="azure_resource_name">Resource name</label>
            <input id="azure_resource_name" className="input" {...field('azure_resource_name')} placeholder="e.g. my-company" required />
            <p style={helpTextStyle}>The resource subdomain in <code>https://&lt;resource&gt;.openai.azure.com</code>.</p>
          </div>
          <div className="form-group">
            <label htmlFor="azure_deployment_name">Deployment name</label>
            <input id="azure_deployment_name" className="input" {...field('azure_deployment_name')} placeholder="e.g. gpt-4o-prod" required />
          </div>
          <div className="form-group">
            <label htmlFor="azure_api_version">API version</label>
            <input id="azure_api_version" className="input" {...field('azure_api_version')} placeholder="e.g. 2024-06-01" required />
          </div>
        </>
      ) : form.connector_type === 'openai_compatible' ? (
        <>
          <div className="form-group">
            <label htmlFor="base_url">Base URL</label>
            <input id="base_url" className="input" {...field('base_url')} placeholder="http://127.0.0.1:11434/v1" required />
            <p style={helpTextStyle}>
              HTTPS is required for public hosts. HTTP is only allowed for loopback (<code>127.0.0.1</code>, <code>localhost</code>) and private (RFC1918) IPs.
            </p>
          </div>
          <div className="form-group">
            <label htmlFor="bearer">Bearer token (optional)</label>
            <input id="bearer" className="input" type="password" {...field('bearer')} />
          </div>
          <details style={{ marginTop: '1rem' }}>
            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
              Want to use your ChatGPT Plus / Pro subscription?
            </summary>
            <p style={{ marginTop: '0.5rem' }}>
              Install{' '}
              <a href="https://github.com/NousResearch/hermes-agent" target="_blank" rel="noreferrer">Hermes Agent</a>
              , run <code>hermes proxy</code>, and paste the URL it prints below. Your ChatGPT account never leaves your machine — WrzDJ only talks to your local Hermes proxy.
            </p>
          </details>
        </>
      ) : (
        <div className="form-group">
          <label htmlFor="api_key">API key</label>
          <input
            id="api_key"
            className="input"
            type="password"
            {...field('api_key')}
            placeholder={API_KEY_PLACEHOLDERS[form.connector_type] ?? API_KEY_PLACEHOLDER_DEFAULT}
            required
          />
        </div>
      )}

      {form.connector_type !== 'bedrock' && (
        <div className="form-group">
          <label htmlFor="model_hint">Model (optional)</label>
          {form.connector_type === 'openrouter_apikey' && models.length > 0 ? (
            <>
              <select
                id="model_hint"
                className="input"
                value={form.model_hint}
                onChange={(event) => onFieldChange('model_hint', event.target.value)}
              >
                <option value="">Default (openai/gpt-4o-mini)</option>
                {models.map((model) => <option key={model.id} value={model.id}>{model.name} ({model.id})</option>)}
              </select>
              <p style={helpTextStyle}>
                Each model routes through OpenRouter and bills your account at that model&apos;s OpenRouter rate (see openrouter.ai/models for per-token pricing).
              </p>
            </>
          ) : (
            <input
              id="model_hint"
              className="input"
              {...field('model_hint')}
              placeholder={MODEL_HINT_PLACEHOLDERS[form.connector_type] ?? MODEL_HINT_PLACEHOLDER_DEFAULT}
            />
          )}
        </div>
      )}
    </>
  );
}
