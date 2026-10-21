import type { CollectionSettingsResponse } from '@/lib/api';
import PreEventVotingTab from './PreEventVotingTab';

interface PreEventSettingsSectionProps {
  code: string;
  eventName: string;
  settings: CollectionSettingsResponse | null;
  loading: boolean;
  error: string | null;
  tidalConnected: boolean;
  tidalIntegrationEnabled: boolean;
  onReload: () => void;
  onSettingsChange: (next: Partial<CollectionSettingsResponse>) => void;
}

export function PreEventSettingsSection({
  code,
  eventName,
  settings,
  loading,
  error,
  tidalConnected,
  tidalIntegrationEnabled,
  onReload,
  onSettingsChange,
}: PreEventSettingsSectionProps) {
  return (
    <section aria-label="Pre-event settings">
      {loading && (
        <div role="status" style={{ color: 'var(--text-secondary)', margin: '1rem 0' }}>
          {settings ? 'Refreshing pre-event settings...' : 'Loading pre-event settings...'}
        </div>
      )}
      {error && (
        <div
          role="alert"
          style={{
            background: 'var(--color-danger-subtle)',
            color: 'var(--color-danger)',
            padding: '0.75rem 1rem',
            borderRadius: '0.5rem',
            margin: '1rem 0',
          }}
        >
          <span>{error}</span>
          {settings && <span> Showing the last loaded settings.</span>}
          <button
            className="btn btn-sm"
            style={{ marginLeft: '0.75rem' }}
            disabled={loading}
            onClick={onReload}
          >
            Retry pre-event settings
          </button>
        </div>
      )}
      {settings && (
        <>
          <button
            className="btn btn-sm"
            style={{ margin: '0.5rem 0' }}
            disabled={loading}
            onClick={onReload}
          >
            Refresh pre-event settings
          </button>
          <PreEventVotingTab
            event={{
              code,
              name: eventName,
              collection_opens_at: settings.collection_opens_at,
              live_starts_at: settings.live_starts_at,
              submission_cap_per_guest: settings.submission_cap_per_guest,
              collection_phase_override: settings.collection_phase_override,
              phase: settings.phase,
              tidal_sync_enabled: settings.tidal_sync_enabled,
              tidal_collection_playlist_id: settings.tidal_collection_playlist_id,
              tidal_collection_bidirectional: settings.tidal_collection_bidirectional,
            }}
            tidalConnected={tidalConnected}
            tidalIntegrationEnabled={tidalIntegrationEnabled}
            onEventChange={onSettingsChange}
          />
        </>
      )}
    </section>
  );
}
