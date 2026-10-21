'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { LlmConnector, LlmFeatureKey, LlmFeaturePreferences } from '@/lib/api/types';

const FEATURE_LABELS: Record<string, string> = {
  recommendation: 'Recommendations',
  set_builder: 'Set builder',
};

export function FeaturePreferencesSection({ connectors }: { connectors: LlmConnector[] }) {
  const [preferences, setPreferences] = useState<LlmFeaturePreferences | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    api.listLlmFeaturePreferences()
      .then((data) => {
        if (!active) return;
        setPreferences(data);
        setError('');
      })
      .catch(() => {
        if (!active) return;
        setPreferences(null);
        setError('Could not load per-feature defaults. Please try again later.');
      });
    return () => { active = false; };
  }, []);

  const updatePreference = async (feature: LlmFeatureKey, value: string) => {
    try {
      const updated = value === ''
        ? await api.clearLlmFeaturePreference(feature)
        : await api.setLlmFeaturePreference({ feature, connector_id: Number(value) });
      setPreferences(updated);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update feature default');
    }
  };

  if (!preferences) {
    if (!error) return null;
    return (
      <section style={{ marginTop: '2rem' }}>
        <h3 style={{ marginTop: 0 }}>Per-feature defaults</h3>
        <p role="alert" style={{ color: 'var(--color-danger)' }}>{error}</p>
      </section>
    );
  }
  if (preferences.known_features.length === 0) return null;
  const activeConnectors = connectors.filter((connector) => connector.status === 'active');
  return (
    <section style={{ marginTop: '2rem' }}>
      <h3 style={{ marginTop: 0 }}>Per-feature defaults</h3>
      <p style={{ color: 'var(--text-secondary)' }}>
        Pin a specific provider to each AI feature. Unpinned features use your account
        default (or most-recently-used) connector. Inactive connectors are skipped
        automatically.
      </p>
      {error && <div style={{ color: 'var(--color-danger)' }}>{error}</div>}
      {preferences.known_features.map((feature) => {
        const current = preferences.preferences.find((item) => item.feature === feature)?.connector_id ?? '';
        const selectId = `feature-pref-${feature}`;
        return (
          <div className="form-group" key={feature}>
            <label htmlFor={selectId}>{FEATURE_LABELS[feature] ?? feature}</label>
            <select id={selectId} className="input" value={current === '' ? '' : String(current)} onChange={(event) => updatePreference(feature as LlmFeatureKey, event.target.value)}>
              <option value="">Use account default</option>
              {activeConnectors.map((connector) => <option key={connector.id} value={String(connector.id)}>{connector.display_name}</option>)}
            </select>
          </div>
        );
      })}
    </section>
  );
}
