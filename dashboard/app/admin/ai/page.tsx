'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import type { AISettings, AIModelInfo } from '@/lib/api-types';
import { useAdminPage } from '@/lib/useAdminPage';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';

const PAGE_ID = 'admin-ai';

export default function AdminAISettingsPage() {
  const [models, setModels] = useState<AIModelInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

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
    </div>
  );
}
