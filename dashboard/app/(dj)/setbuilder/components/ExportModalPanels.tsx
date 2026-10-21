import type {
  ExportFileFormat,
  ExportPreflight,
  ExportSpotifyResult,
  ExportTidalResult,
  ExportAppleMusicResult,
  UnresolvedTrack,
} from '@/lib/api/types';

import sharedStyles from '../setbuilder-shared.module.css';

const XML_PLATFORMS = ['rekordbox', 'enginedj', 'lexicon'] as const;

interface ConfirmStageProps {
  preflight: ExportPreflight;
  platformId: string;
  skipUnresolved: boolean;
  canExport: boolean;
  fileDownloaded: string | null;
  onSkip: () => void;
  onCancel: () => void;
  onTidalExport: () => void;
  onSpotifyExport: () => void;
  onAppleMusicExport: () => void;
  onConnectSpotify: () => void;
  onConnectAppleMusic: () => void;
  appleMusicConnecting: boolean;
  onFileExport: (format: ExportFileFormat) => void;
  exporting: boolean;
  downloading: boolean;
}

export function ConfirmStage({
  preflight,
  platformId,
  skipUnresolved,
  canExport,
  fileDownloaded,
  onSkip,
  onCancel,
  onTidalExport,
  onSpotifyExport,
  onAppleMusicExport,
  onConnectSpotify,
  onConnectAppleMusic,
  appleMusicConnecting,
  onFileExport,
  exporting,
  downloading,
}: ConfirmStageProps) {
  return (
    <div>
      <div
        style={{
          marginBottom: '0.75rem',
          padding: '0.6rem 0.7rem',
          border: '1px solid var(--border)',
          borderRadius: '8px',
          background: 'var(--bg)',
          fontSize: '0.75rem',
        }}
      >
        <div>
          <strong>{preflight.total}</strong> tracks in set &mdash;{' '}
          <strong>{preflight.resolved_count}</strong> resolved
        </div>
        {preflight.source === 'pool' && (
          <div
            style={{
              marginTop: '0.35rem',
              color: 'var(--text-secondary)',
              fontSize: '0.6875rem',
            }}
          >
            Timeline is empty — exporting the pool ({preflight.total} tracks)
          </div>
        )}
      </div>

      {platformId === 'tidal' && preflight.tidal_connected === false && (
        <div className={sharedStyles.imError} style={connectionWarningStyle}>
          Connect Tidal first — link it from your event&apos;s Cloud Providers card.
        </div>
      )}

      {platformId === 'spotify' && preflight.spotify_connected === false && (
        <div className={sharedStyles.imError} style={connectionWarningStyle}>
          Link Spotify to create a playlist in your account.
          <button className="btn btn-sm" onClick={onConnectSpotify} style={connectButtonStyle}>
            Connect Spotify
          </button>
        </div>
      )}

      {platformId === 'applemusic' && preflight.apple_music_connected === false && (
        <div className={sharedStyles.imError} style={connectionWarningStyle}>
          Link Apple Music to create a playlist in your account.
          <button
            className="btn btn-sm"
            onClick={onConnectAppleMusic}
            disabled={appleMusicConnecting}
            style={connectButtonStyle}
          >
            {appleMusicConnecting ? 'Connecting Apple Music…' : 'Connect Apple Music'}
          </button>
        </div>
      )}

      {preflight.unresolved.length > 0 && !skipUnresolved && (
        <UnresolvedInterrupt unresolved={preflight.unresolved} onSkip={onSkip} onCancel={onCancel} />
      )}

      {canExport && platformId === 'tidal' && preflight.tidal_connected !== false && (
        <button
          className="btn btn-primary btn-sm"
          disabled={exporting}
          onClick={onTidalExport}
          style={exportButtonStyle}
        >
          {exporting ? 'Exporting…' : 'Export to Tidal'}
        </button>
      )}

      {canExport && platformId === 'spotify' && preflight.spotify_connected !== false && (
        <button
          className="btn btn-primary btn-sm"
          disabled={exporting}
          onClick={onSpotifyExport}
          style={exportButtonStyle}
        >
          {exporting ? 'Exporting…' : 'Export to Spotify'}
        </button>
      )}

      {canExport && platformId === 'applemusic' && preflight.apple_music_connected !== false && (
        <button
          className="btn btn-primary btn-sm"
          disabled={exporting}
          onClick={onAppleMusicExport}
          style={exportButtonStyle}
        >
          {exporting ? 'Exporting…' : 'Export to Apple Music'}
        </button>
      )}

      {canExport && (XML_PLATFORMS as readonly string[]).includes(platformId) && (
        <div style={{ marginTop: '0.5rem' }}>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className="btn btn-primary btn-sm"
              disabled={exporting || downloading}
              onClick={() => onFileExport(platformId as ExportFileFormat)}
            >
              {downloading ? 'Preparing…' : 'Download .xml'}
            </button>
            {fileDownloaded && <DownloadedLabel />}
          </div>
          {platformId !== 'rekordbox' && (
            <div style={importGuidanceStyle}>
              Engine DJ and Lexicon both import this Rekordbox XML. Set the XML path in the
              app, import the playlist, then relink tracks to your local audio files.
            </div>
          )}
        </div>
      )}

      {canExport && platformId === 'm3u' && (
        <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button
            className="btn btn-primary btn-sm"
            disabled={exporting || downloading}
            onClick={() => onFileExport('m3u')}
          >
            Download .m3u8
          </button>
          <button
            className="btn btn-sm"
            style={{ background: 'var(--surface-raised)' }}
            disabled={exporting || downloading}
            onClick={() => onFileExport('txt')}
          >
            Download .txt
          </button>
          {fileDownloaded && <DownloadedLabel />}
        </div>
      )}
    </div>
  );
}

function UnresolvedInterrupt({
  unresolved,
  onSkip,
  onCancel,
}: {
  unresolved: UnresolvedTrack[];
  onSkip: () => void;
  onCancel: () => void;
}) {
  return (
    <div>
      <div className={sharedStyles.imError}>
        {unresolved.length} track{unresolved.length !== 1 ? 's' : ''} couldn&apos;t be resolved
        — they will NOT be exported unless you skip them.
      </div>
      <div style={unresolvedListStyle}>
        {unresolved.map((track) => {
          const display = track.title || track.track_id || '—';
          return (
            <div key={track.position} style={unresolvedRowStyle}>
              <div style={{ fontWeight: 600 }}>
                {track.artist ? `${track.artist} – ${display}` : display}
              </div>
              <div style={{ color: 'var(--text-secondary)' }}>{track.reason}</div>
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="btn btn-sm" onClick={onCancel} aria-label="Cancel">
          Cancel
        </button>
        <button className="btn btn-primary btn-sm" onClick={onSkip}>
          Skip {unresolved.length} &amp; continue
        </button>
      </div>
    </div>
  );
}

export function TidalDonePanel({ result }: { result: ExportTidalResult }) {
  return <ProviderDonePanel label="Tidal" result={result} />;
}

export function SpotifyDonePanel({ result }: { result: ExportSpotifyResult }) {
  return <ProviderDonePanel label="Spotify" result={result} />;
}

export function AppleMusicDonePanel({ result }: { result: ExportAppleMusicResult }) {
  return (
    <ProviderDonePanel label="Apple Music" result={result} showLink={Boolean(result.playlist_url)} />
  );
}

function ProviderDonePanel({
  label,
  result,
  showLink = true,
}: {
  label: string;
  result: { added: number; skipped: number; playlist_url: string | null };
  showLink?: boolean;
}) {
  return (
    <div>
      <div style={successPanelStyle}>
        <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '0.35rem' }}>
          Playlist created
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
          {result.added} tracks added{result.skipped > 0 ? `, ${result.skipped} skipped` : ''}
        </div>
      </div>
      {showLink && result.playlist_url && (
        <a
          href={result.playlist_url}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-primary btn-sm"
          style={{ display: 'inline-block', textDecoration: 'none' }}
        >
          Open in {label}
        </a>
      )}
    </div>
  );
}

function DownloadedLabel() {
  return (
    <span style={{ fontSize: '0.75rem', color: 'var(--color-success, #22c55e)', alignSelf: 'center' }}>
      Downloaded ✓
    </span>
  );
}

const connectionWarningStyle = {
  borderColor: 'rgba(251,191,36,0.4)',
  background: 'rgba(251,191,36,0.1)',
  color: '#fbbf24',
};
const connectButtonStyle = { display: 'block', marginTop: '0.5rem' };
const exportButtonStyle = { marginTop: '0.5rem', width: '100%' };
const importGuidanceStyle = {
  marginTop: '0.5rem',
  fontSize: '0.6875rem',
  color: 'var(--text-secondary)',
  lineHeight: 1.4,
};
const unresolvedListStyle = {
  maxHeight: '200px',
  overflowY: 'auto' as const,
  border: '1px solid var(--border-subtle)',
  borderRadius: '8px',
  marginBottom: '0.75rem',
};
const unresolvedRowStyle = {
  padding: '0.45rem 0.65rem',
  borderBottom: '1px solid var(--border-subtle)',
  fontSize: '0.6875rem',
};
const successPanelStyle = {
  padding: '0.75rem',
  border: '1px solid rgba(34,197,94,0.3)',
  borderRadius: '8px',
  background: 'rgba(34,197,94,0.08)',
  marginBottom: '0.75rem',
};
