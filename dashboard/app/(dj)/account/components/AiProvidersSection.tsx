'use client';

import { useEffect, useMemo, useState } from 'react';

import { api } from '@/lib/api';
import type {
  LlmConnector,
  LlmConnectorType,
  LlmDjPolicy,
} from '@/lib/api/types';
import { AiProviderConnectorCard } from './AiProviderConnectorCard';
import { FeaturePreferencesSection } from './FeaturePreferencesSection';
import { ProviderCreationSection } from './ProviderCreationSection';

/**
 * DJ-facing AI connector management UI (connect / test / delete, model hint,
 * Hermes onboarding). Relocated from the standalone `/settings/ai` route into
 * the `/account` page (issue #357). The component assumes the parent already
 * enforces authentication — it does no auth gating of its own.
 *
 * Fail-closed behavior is preserved: when the DJ-scoped policy endpoint can't
 * be read, NO provider types are offered rather than leaking every type.
 */
export default function AiProvidersSection() {
  const [policy, setPolicy] = useState<LlmDjPolicy | null>(null);
  const [connectors, setConnectors] = useState<LlmConnector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // Only one provider stream may run at a time; each row owns its own output.
  const [streamingId, setStreamingId] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
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
  }, []);

  const allowedTypes = useMemo<LlmConnectorType[]>(() => {
    // Fail closed: when the policy can't be read, offer no providers rather than
    // surfacing every type and letting the DJ pick one the admin disabled (the
    // create call would 403). The server is the source of truth for the set.
    if (!policy) return [];
    return policy.allowed_connector_types as LlmConnectorType[];
  }, [policy]);

  const handleTest = async (id: number): Promise<string> => {
    const result = await api.testLlmConnector(id);
    // Refresh the row so updated status renders.
    const fresh = await api.listLlmConnectors();
    setConnectors(fresh);
    return result.ok ? 'OK' : `Failed: ${result.error_code ?? 'unknown'}`;
  };

  const handleStreamTest = async (id: number, onTextDelta: (text: string) => void) => {
    setStreamingId(id);
    try {
      await api.streamConnectorTest(id, (chunk) => {
        if (chunk.text_delta) onTextDelta(chunk.text_delta);
      });
    } finally {
      setStreamingId(null);
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

  // Set / unset the per-DJ explicit default (issue #336). Optimistic update on
  // the full list keeps the radio state consistent (exactly one row is default
  // at any time) without waiting for a refetch.
  const handleSetDefault = async (id: number) => {
    try {
      const updated = await api.setLlmConnectorDefault(id);
      setConnectors((prev) =>
        prev.map((c) =>
          c.id === updated.id
            ? updated
            : c.user_id === updated.user_id
            ? { ...c, is_default: false }
            : c,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set default');
    }
  };

  const handleUnsetDefault = async (id: number) => {
    try {
      const updated = await api.unsetLlmConnectorDefault(id);
      setConnectors((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear default');
    }
  };

  return (
    <div>
      <h2 style={{ marginTop: 0, marginBottom: '1.25rem', fontSize: '1.1rem' }}>
        AI / Model providers
      </h2>

      <p style={{ color: 'var(--text-secondary)' }}>
        Connect your own LLM provider so AI-assisted features (recommendations, etc.) bill to
        your account. Credentials are encrypted at rest. Calls consume your account&apos;s API or
        subscription quota directly.
      </p>

      {loading && <div className="loading">Loading…</div>}
      {error && <div style={{ color: 'var(--color-danger)', marginTop: '1rem' }}>{error}</div>}

      <section style={{ marginTop: '2rem' }}>
        <h3 style={{ marginTop: 0 }}>Connected providers</h3>
        {/*
          Connector-less DJ banners. When an org connector exists AND the admin
          fallback toggle is on, this DJ's AI calls run on the house connector
          (house-billed) — say so. Otherwise AI features are simply unavailable.
          A failed policy fetch leaves `policy` null, which renders the danger
          banner — fail-closed messaging, matching `allowedTypes` above. The
          "connect a provider" instruction is only appended when the admin
          policy actually allows creating one (otherwise the section below says
          creation is disabled, and the copy would contradict it). A hard load
          failure (`error`) suppresses both banners — we don't know whether the
          DJ has connectors, so we make no availability claims.
        */}
        {connectors.length === 0 && !loading && !error && (
          policy?.org_fallback_available ? (
            <div
              style={{
                background: 'var(--color-warning-subtle)',
                color: 'var(--color-warning)',
                padding: '0.75rem 1rem',
                borderRadius: '0.5rem',
                fontSize: '0.875rem',
              }}
            >
              You&apos;re using the organization&apos;s connector — usage is billed to the
              organization. Connect your own provider below to use your own account.
            </div>
          ) : (
            <div
              style={{
                background: 'var(--color-danger-subtle)',
                color: 'var(--color-danger)',
                padding: '0.75rem 1rem',
                borderRadius: '0.5rem',
                fontSize: '0.875rem',
              }}
            >
              {allowedTypes.length > 0
                ? 'AI features unavailable — connect a provider below to enable them.'
                : 'AI features unavailable.'}
            </div>
          )
        )}
        {connectors.map((c) => {
          return (
            <AiProviderConnectorCard
              key={c.id}
              connector={c}
              streaming={streamingId !== null}
              isStreaming={streamingId === c.id}
              onTest={handleTest}
              onStreamTest={handleStreamTest}
              onDelete={handleDelete}
              onSetDefault={handleSetDefault}
              onUnsetDefault={handleUnsetDefault}
            />
          );
        })}
      </section>

      <FeaturePreferencesSection connectors={connectors} />

      <ProviderCreationSection
        allowedTypes={allowedTypes}
        loading={loading}
        onCreated={(created) => setConnectors((current) => [created, ...current])}
      />
    </div>
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
