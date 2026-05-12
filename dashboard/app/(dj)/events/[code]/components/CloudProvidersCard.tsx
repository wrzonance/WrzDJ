'use client';

import type { BeatportStatus, TidalStatus } from '@/lib/api';
import { Tooltip } from '@/components/Tooltip';

interface CloudProvidersCardProps {
  tidalStatus: TidalStatus | null;
  tidalSyncEnabled: boolean;
  togglingTidalSync: boolean;
  onToggleTidalSync: () => void;
  onConnectTidal: () => void;
  onDisconnectTidal: () => void;
  beatportStatus: BeatportStatus | null;
  beatportSyncEnabled: boolean;
  togglingBeatportSync: boolean;
  onToggleBeatportSync: () => void;
  onConnectBeatport: () => void;
  onDisconnectBeatport: () => void;
}

const PLACEHOLDER_PROVIDERS = [
  { name: 'Beatsource', color: '#ff6b00' },
  { name: 'SoundCloud', color: '#ff5500' },
  { name: 'Amazon Music', color: '#25d1da' },
];

export function CloudProvidersCard({
  tidalStatus,
  tidalSyncEnabled,
  togglingTidalSync,
  onToggleTidalSync,
  onConnectTidal,
  onDisconnectTidal,
  beatportStatus,
  beatportSyncEnabled,
  togglingBeatportSync,
  onToggleBeatportSync,
  onConnectBeatport,
  onDisconnectBeatport,
}: CloudProvidersCardProps) {
  return (
    <div className="card" style={{ marginBottom: '1rem', padding: '1rem' }}>
      <div style={{ marginBottom: '1rem' }}>
        <span style={{ fontWeight: 600 }}>Cloud Providers</span>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.25rem 0 0' }}>
          Sync accepted requests to streaming service playlists
        </p>
      </div>

      {/* Column headers */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          gap: '0.5rem',
          marginBottom: '0.375rem',
          paddingRight: '0.75rem',
        }}
      >
        <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', minWidth: '100px', textAlign: 'center' }}>
          Playlist Sync
        </span>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', minWidth: '90px', textAlign: 'center' }}>
          Account
        </span>
      </div>

      {/* Tidal - functional */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.75rem',
          background: 'var(--surface-raised)',
          borderRadius: '6px',
          marginBottom: '0.5rem',
          opacity: tidalStatus?.integration_enabled === false ? 0.5 : 1,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>Tidal</span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}></span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {tidalStatus?.integration_enabled === false ? (
            <span style={{ color: 'var(--text-tertiary)', fontSize: '0.875rem' }}>Unavailable</span>
          ) : tidalStatus?.linked ? (
            <>
              <span style={{ color: 'var(--color-success)', fontSize: '0.875rem' }}>Connected</span>
              <button
                className={`btn btn-sm ${tidalSyncEnabled ? 'btn-success' : ''}`}
                style={{ minWidth: '100px', background: tidalSyncEnabled ? undefined : 'var(--surface-raised)' }}
                onClick={onToggleTidalSync}
                disabled={togglingTidalSync}
              >
                {togglingTidalSync ? '...' : tidalSyncEnabled ? 'Enabled' : 'Disabled'}
              </button>
              <Tooltip description="Disconnect Tidal account and remove saved tokens">
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--text-tertiary)', color: 'white', minWidth: '90px' }}
                  onClick={onDisconnectTidal}
                >
                  Disconnect
                </button>
              </Tooltip>
            </>
          ) : (
            <button
              className="btn btn-sm"
              style={{ background: '#0066ff' }}
              onClick={onConnectTidal}
            >
              Connect Tidal
            </button>
          )}
        </div>
      </div>

      {/* Beatport - functional */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.75rem',
          background: 'var(--surface-raised)',
          borderRadius: '6px',
          marginBottom: '0.5rem',
          opacity: beatportStatus?.integration_enabled === false ? 0.5 : 1,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>Beatport</span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}></span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {beatportStatus?.integration_enabled === false ? (
            <span style={{ color: 'var(--text-tertiary)', fontSize: '0.875rem' }}>Unavailable</span>
          ) : beatportStatus?.linked ? (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.25rem' }}>
                <span style={{ color: '#01ff28', fontSize: '0.875rem' }}>Connected</span>
                {beatportStatus.subscription && ['bp_link', 'bp_pro', 'streaming'].includes(beatportStatus.subscription) ? (
                  <span style={{ fontSize: '0.65rem', color: 'var(--color-success)', background: 'var(--color-success-subtle)', padding: '0.125rem 0.375rem', borderRadius: '9999px' }}>
                    Full Streaming Access
                  </span>
                ) : (
                  <span style={{ fontSize: '0.65rem', color: 'var(--color-warning)', background: 'var(--color-warning-subtle)', padding: '0.125rem 0.375rem', borderRadius: '9999px' }}>
                    Purchased Library Only
                  </span>
                )}
              </div>
              <button
                className={`btn btn-sm ${beatportSyncEnabled ? 'btn-success' : ''}`}
                style={{ minWidth: '100px', background: beatportSyncEnabled ? undefined : 'var(--surface-raised)' }}
                onClick={onToggleBeatportSync}
                disabled={togglingBeatportSync}
              >
                {togglingBeatportSync ? '...' : beatportSyncEnabled ? 'Enabled' : 'Disabled'}
              </button>
              <Tooltip description="Disconnect Beatport account and remove saved tokens">
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--text-tertiary)', color: 'white', minWidth: '90px' }}
                  onClick={onDisconnectBeatport}
                >
                  Disconnect
                </button>
              </Tooltip>
            </>
          ) : (
            <button
              className="btn btn-sm"
              style={{ background: '#01ff28', color: '#000' }}
              onClick={onConnectBeatport}
            >
              Connect Beatport
            </button>
          )}
        </div>
      </div>

      {/* Placeholder providers */}
      {PLACEHOLDER_PROVIDERS.map((provider) => (
        <div
          key={provider.name}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0.75rem',
            background: 'var(--surface-raised)',
            borderRadius: '6px',
            marginBottom: '0.5rem',
            opacity: 0.5,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>{provider.name}</span>
          </div>
          <button
            className="btn btn-sm"
            style={{ background: 'var(--surface-raised)' }}
            disabled
          >
            Coming Soon
          </button>
        </div>
      ))}
    </div>
  );
}
