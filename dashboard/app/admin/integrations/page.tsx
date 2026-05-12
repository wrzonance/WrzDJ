'use client';

import { useState } from 'react';
import type {
  IntegrationServiceStatus,
  CapabilityStatus,
} from '@/lib/api';
import { api } from '@/lib/api';
import { useAdminPage } from '@/lib/useAdminPage';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';

const PAGE_ID = 'admin-integrations';

const BADGE_LABELS: Record<CapabilityStatus, string> = {
  yes: 'YES',
  no: 'NO',
  not_implemented: 'N/A',
  configured: 'CONFIGURED',
  not_configured: 'NOT CONFIGURED',
};

const BADGE_CLASSES: Record<CapabilityStatus, string> = {
  yes: 'badge-status yes',
  no: 'badge-status no',
  not_implemented: 'badge-status not-implemented',
  configured: 'badge-status configured',
  not_configured: 'badge-status not-configured',
};

function CapabilityBadge({ status }: { status: CapabilityStatus }) {
  return <span className={BADGE_CLASSES[status]}>{BADGE_LABELS[status]}</span>;
}

export default function AdminIntegrationsPage() {
  const [error, setError] = useState('');
  const [checking, setChecking] = useState<Record<string, boolean>>({});
  const [toggling, setToggling] = useState<Record<string, boolean>>({});

  const { data: services, loading, error: loadError, setData: setServices, reload: _reload } = useAdminPage<IntegrationServiceStatus[]>({
    pageId: PAGE_ID,
    loader: () => api.getIntegrations().then((d) => d.services),
    onError: () => 'Failed to load integration status',
  });

  const handleToggle = async (service: string, currentEnabled: boolean) => {
    setToggling((prev) => ({ ...prev, [service]: true }));
    try {
      const result = await api.toggleIntegration(service, !currentEnabled);
      setServices((prev) =>
        prev?.map((s) =>
          s.service === service ? { ...s, enabled: result.enabled } : s
        ) ?? prev
      );
    } catch {
      setError(`Failed to toggle ${service}`);
    } finally {
      setToggling((prev) => ({ ...prev, [service]: false }));
    }
  };

  const handleCheck = async (service: string) => {
    setChecking((prev) => ({ ...prev, [service]: true }));
    try {
      const result = await api.checkIntegrationHealth(service);
      setServices((prev) =>
        prev?.map((s) =>
          s.service === service
            ? {
                ...s,
                capabilities: result.capabilities,
                last_check_error: result.error,
              }
            : s
        ) ?? prev
      );
    } catch {
      setError(`Health check failed for ${service}`);
    } finally {
      setChecking((prev) => ({ ...prev, [service]: false }));
    }
  };

  if (loading) {
    return (
      <div className="container">
        <div className="loading">Loading integrations...</div>
      </div>
    );
  }

  return (
    <div className="container">
      <HelpButton page={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />
      <h1 style={{ marginBottom: '0.5rem' }}>Integrations</h1>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '2rem' }}>
        Monitor and control external service integrations. Disabled services
        show &quot;currently unavailable&quot; to DJs.
      </p>

      {(error || loadError) && (
        <div
          style={{
            color: 'var(--color-danger)',
            marginBottom: '1rem',
            padding: '0.75rem',
            background: 'rgba(239, 68, 68, 0.1)',
            borderRadius: '6px',
          }}
        >
          {error || loadError}
        </div>
      )}

      <HelpSpot spotId="admin-service-table" page={PAGE_ID} order={1} title="Service Status" description="Monitor Spotify, Tidal, Beatport, and Bridge integrations.">
        <div className="card" style={{ overflow: 'auto' }}>
          <table className="integration-table">
            <thead>
              <tr>
                <th>Service</th>
                <th>
                  <HelpSpot spotId="admin-service-toggles" page={PAGE_ID} order={2} title="Enable/Disable" description="Toggle services on/off. Disabled services show &quot;unavailable&quot; to DJs.">
                    <span>Enabled</span>
                  </HelpSpot>
                </th>
                <th>Auth / Login</th>
                <th>Catalog Search</th>
                <th>Playlist Sync</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(services ?? []).map((svc) => (
                <tr key={svc.service}>
                  <td>
                    <div style={{ fontWeight: 500 }}>{svc.display_name}</div>
                    {svc.last_check_error && (
                      <div
                        style={{
                          color: 'var(--color-danger)',
                          fontSize: '0.75rem',
                          marginTop: '0.25rem',
                        }}
                      >
                        {svc.last_check_error}
                      </div>
                    )}
                  </td>
                  <td>
                    <button
                      className={`toggle-switch${svc.enabled ? ' active' : ''}`}
                      onClick={() => handleToggle(svc.service, svc.enabled)}
                      disabled={toggling[svc.service]}
                      aria-label={`${svc.enabled ? 'Disable' : 'Enable'} ${svc.display_name}`}
                    />
                  </td>
                  <td>
                    <CapabilityBadge status={svc.capabilities.auth} />
                  </td>
                  <td>
                    <CapabilityBadge status={svc.capabilities.catalog_search} />
                  </td>
                  <td>
                    <CapabilityBadge status={svc.capabilities.playlist_sync} />
                  </td>
                  <td>
                    <button
                      className="btn-check"
                      onClick={() => handleCheck(svc.service)}
                      disabled={checking[svc.service]}
                    >
                      {checking[svc.service] ? 'Checking...' : 'Check Health'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </HelpSpot>

      <HelpSpot spotId="admin-badge-legend" page={PAGE_ID} order={3} title="Badge Legend" description="What each badge means: YES, CONFIGURED, NO, NOT CONFIGURED, N/A.">
        <div
          className="card"
          style={{ marginTop: '1rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}
        >
          <strong style={{ color: 'var(--text)' }}>Badge Legend</strong>
          <div
            style={{
              display: 'flex',
              gap: '1rem',
              flexWrap: 'wrap',
              marginTop: '0.75rem',
            }}
          >
            <span>
              <span className="badge-status yes">YES</span> Working
            </span>
            <span>
              <span className="badge-status configured">CONFIGURED</span>{' '}
              Credentials set, untested
            </span>
            <span>
              <span className="badge-status no">NO</span> Check failed
            </span>
            <span>
              <span className="badge-status not-configured">NOT CONFIGURED</span>{' '}
              No credentials
            </span>
            <span>
              <span className="badge-status not-implemented">N/A</span> Not
              supported
            </span>
          </div>
        </div>
      </HelpSpot>
    </div>
  );
}
