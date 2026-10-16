'use client';

/**
 * Setlist export modal (issue #396).
 *
 * Stage flow:
 *   'pick' → user selects platform
 *   'checking' → preflight API call in flight
 *   'confirm' → summary + optional unresolved interrupt
 *   'exporting' → export API call in flight
 *   'done' → success (Tidal only; file downloads dismiss inline)
 */

import { useRef, useState } from 'react';
import { ApiError, api } from '@/lib/api';
import type {
  ExportPreflight,
  ExportTarget,
  ExportFileFormat,
  ExportTidalResult,
  ExportSpotifyResult,
  ExportAppleMusicResult,
  ExportAppleMusicRecoveryRequest,
  SetDetail,
  UnresolvedTrack,
} from '@/lib/api-types';
import styles from '../setbuilder.module.css';
import { authorizeAppleMusic } from '@/lib/apple-music-auth';

// ---------------------------------------------------------------------------
// Platform catalogue
// ---------------------------------------------------------------------------

const PLATFORMS = [
  { id: 'tidal' as const, label: 'Tidal', sub: 'Playlist in your Tidal account', available: true },
  {
    id: 'rekordbox' as const,
    label: 'Rekordbox XML',
    sub: 'DJ_PLAYLISTS import file',
    available: true,
  },
  {
    id: 'm3u' as const,
    label: 'M3U / .txt',
    sub: 'Universal playlist / plaintext',
    available: true,
  },
  {
    id: 'enginedj' as const,
    label: 'Engine DJ XML',
    sub: 'Imports via Rekordbox XML — relink on import',
    available: true,
  },
  {
    id: 'lexicon' as const,
    label: 'Lexicon',
    sub: 'Imports via Rekordbox XML — relink on import',
    available: true,
  },
  { id: 'serato' as const, label: 'Serato .crate', sub: '', available: false },
  { id: 'spotify' as const, label: 'Spotify', sub: 'Private playlist in your Spotify account', available: true },
  { id: 'applemusic' as const, label: 'Apple Music', sub: 'Playlist in your Apple Music account', available: true },
];

// Targets that emit the Rekordbox DJ_PLAYLISTS XML. Engine DJ and Lexicon have
// no proprietary import format — both ingest this XML — so they share one
// download path with rekordbox.
const XML_PLATFORMS = ['rekordbox', 'enginedj', 'lexicon'] as const;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ExportModalProps {
  set: SetDetail;
  onClose: () => void;
  /** Patch the page's copy after a Tidal export marks the set exported. */
  onSetUpdated: (patch: Partial<SetDetail>) => void;
}

// ---------------------------------------------------------------------------
// Download helper
// ---------------------------------------------------------------------------

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function buildFallbackName(setName: string, ext: string): string {
  const safe = setName.replace(/[^A-Za-z0-9 _-]/g, '').trim() || 'set';
  return `${safe}.${ext}`;
}

function errMessage(e: unknown): string {
  if (e instanceof Error && e.message) return e.message;
  return 'Export failed — try again';
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type Stage = 'pick' | 'checking' | 'confirm' | 'exporting' | 'unconfirmed' | 'recovered' | 'done';
type AppleMusicUnconfirmed = { message: string; playlistId: string | null };

export default function ExportModal({ set, onClose, onSetUpdated }: ExportModalProps) {
  const [stage, setStage] = useState<Stage>(
    set.apple_music_export_uncertain ? 'unconfirmed' : 'pick',
  );
  const [activePlatform, setActivePlatform] = useState<(typeof PLATFORMS)[number] | null>(null);
  const [preflight, setPreflight] = useState<ExportPreflight | null>(null);
  const [skipUnresolved, setSkipUnresolved] = useState(false);
  const [tidalResult, setTidalResult] = useState<ExportTidalResult | null>(null);
  const [spotifyResult, setSpotifyResult] = useState<ExportSpotifyResult | null>(null);
  const [appleMusicResult, setAppleMusicResult] = useState<ExportAppleMusicResult | null>(null);
  const [appleMusicUnconfirmed, setAppleMusicUnconfirmed] = useState<AppleMusicUnconfirmed | null>(null);
  const [recoveryPlaylistId, setRecoveryPlaylistId] = useState(
    set.apple_music_export_recovery_playlist_id ?? '',
  );
  const [confirmPlaylistAbsent, setConfirmPlaylistAbsent] = useState(false);
  const [reconcilingAppleMusic, setReconcilingAppleMusic] = useState(false);
  const [appleMusicRecoveryResult, setAppleMusicRecoveryResult] = useState<'found' | 'absent' | null>(null);
  const [fileDownloaded, setFileDownloaded] = useState<string | null>(null); // filename
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [appleMusicConnecting, setAppleMusicConnecting] = useState(false);
  const appleMusicConnectInFlight = useRef(false);

  // ---- pick a platform ----
  const handlePick = async (platform: (typeof PLATFORMS)[number]) => {
    if (!platform.available) return;
    setActivePlatform(platform);
    setError(null);
    setSkipUnresolved(false);
    setPreflight(null);
    setAppleMusicUnconfirmed(null);
    setFileDownloaded(null);
    setStage('checking');

    const targetMap: Record<'tidal' | 'spotify' | 'applemusic' | 'rekordbox' | 'm3u' | 'enginedj' | 'lexicon', ExportTarget> = {
      tidal: 'tidal',
      spotify: 'spotify',
      applemusic: 'apple_music',
      rekordbox: 'rekordbox',
      m3u: 'm3u',
      enginedj: 'enginedj',
      lexicon: 'lexicon',
    };
    const target = targetMap[platform.id as keyof typeof targetMap];

    try {
      const result = await api.exportPreflight(set.id, target);
      setPreflight(result);
      setStage('confirm');
    } catch (e) {
      setError(
        target === 'apple_music' && e instanceof ApiError && e.status === 503
          ? 'Apple Music export is unavailable because this deployment is not configured.'
          : errMessage(e),
      );
      setStage('pick');
    }
  };

  // ---- handle skip unresolved ----
  const handleSkip = () => {
    setSkipUnresolved(true);
  };

  // ---- Tidal export ----
  const handleTidalExport = async () => {
    setStage('exporting');
    setError(null);
    try {
      const result = await api.exportSetToTidal(set.id, skipUnresolved);
      setTidalResult(result);
      onSetUpdated({
        status: result.status,
        tidal_playlist_id: result.playlist_id,
        exported_at: result.exported_at,
      });
      setStage('done');
    } catch (e) {
      setError(errMessage(e));
      setStage('confirm');
    }
  };

  const handleSpotifyExport = async () => {
    setStage('exporting');
    setError(null);
    try {
      const result = await api.exportSetToSpotify(set.id, skipUnresolved);
      setSpotifyResult(result);
      onSetUpdated({
        status: result.status,
        spotify_playlist_id: result.playlist_id,
        exported_at: result.exported_at,
      });
      setStage('done');
    } catch (e) {
      setError(errMessage(e));
      setStage('confirm');
    }
  };

  const handleConnectSpotify = async () => {
    setError(null);
    try {
      const { authorization_url } = await api.startSpotifyAuthorization();
      window.location.assign(authorization_url);
    } catch (e) {
      setError(errMessage(e));
    }
  };

  const handleAppleMusicExport = async () => {
    setStage('exporting');
    setError(null);
    try {
      const result = await api.exportSetToAppleMusic(set.id, skipUnresolved);
      setAppleMusicResult(result);
      onSetUpdated({
        status: result.status,
        apple_music_playlist_id: result.playlist_id,
        exported_at: result.exported_at,
      });
      setStage('done');
    } catch (e) {
      if (e instanceof ApiError && e.code === 'apple_music_write_uncertain') {
        const detail = e.detail && typeof e.detail === 'object'
          ? e.detail as { playlist_id?: unknown }
          : null;
        const playlistId = typeof detail?.playlist_id === 'string' ? detail.playlist_id : null;
        setAppleMusicUnconfirmed({ message: e.message, playlistId });
        setRecoveryPlaylistId(playlistId ?? '');
        onSetUpdated({
          apple_music_export_uncertain: true,
          apple_music_export_recovery_playlist_id: playlistId,
        });
        setStage('unconfirmed');
        return;
      }
      setError(errMessage(e));
      if (
        e instanceof ApiError &&
        e.status === 400 &&
        /not connected|reconnect/i.test(e.message)
      ) {
        setPreflight(current => (current ? { ...current, apple_music_connected: false } : current));
      }
      setStage('confirm');
    }
  };

  const handleAppleMusicRecovery = async (action: 'playlist_found' | 'playlist_absent') => {
    const playlistId = recoveryPlaylistId.trim();
    if (action === 'playlist_found' && !/^p\.[A-Za-z0-9_-]{1,98}$/.test(playlistId)) return;

    setError(null);
    setReconcilingAppleMusic(true);
    try {
      const request: ExportAppleMusicRecoveryRequest = action === 'playlist_found'
        ? { action, playlist_id: playlistId }
        : { action };
      const result = await api.reconcileAppleMusicExport(set.id, request);
      if (action === 'playlist_found' && result.status !== 'exported') {
        throw new Error('Apple Music did not confirm the playlist. Please check again.');
      }
      if (action === 'playlist_absent' && result.status !== 'ready_to_retry') {
        throw new Error('Apple Music could not update the export status. Please try again.');
      }
      if (action === 'playlist_found') {
        onSetUpdated({
          status: 'exported',
          apple_music_playlist_id: playlistId,
          apple_music_export_uncertain: false,
          apple_music_export_recovery_playlist_id: null,
        });
        setAppleMusicRecoveryResult('found');
      } else {
        onSetUpdated({
          apple_music_export_uncertain: false,
          apple_music_export_recovery_playlist_id: null,
        });
        setAppleMusicRecoveryResult('absent');
      }
      setStage('recovered');
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setReconcilingAppleMusic(false);
    }
  };

  const handleConnectAppleMusic = async () => {
    if (appleMusicConnectInFlight.current) return;
    appleMusicConnectInFlight.current = true;
    setAppleMusicConnecting(true);
    setError(null);
    try {
      const token = await api.getAppleMusicDeveloperToken();
      const musicUserToken = await authorizeAppleMusic(token.developer_token);
      const status = await api.linkAppleMusicAccount(musicUserToken);
      if (!status.linked) throw new Error('Apple Music authorization could not be confirmed.');
      setPreflight(await api.exportPreflight(set.id, 'apple_music'));
    } catch (e) {
      setError(errMessage(e));
    } finally {
      appleMusicConnectInFlight.current = false;
      setAppleMusicConnecting(false);
    }
  };

  // ---- File export (rekordbox / m3u / txt) ----
  const handleFileExport = async (format: ExportFileFormat) => {
    setError(null);
    setDownloading(true);
    const extMap: Record<ExportFileFormat, string> = {
      rekordbox: 'xml',
      m3u: 'm3u8',
      txt: 'txt',
      enginedj: 'xml',
      lexicon: 'xml',
    };
    const fallback = buildFallbackName(set.name, extMap[format]);
    try {
      const { blob, filename } = await api.exportSetFile(set.id, format, skipUnresolved, fallback);
      triggerDownload(blob, filename);
      setFileDownloaded(filename);
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setDownloading(false);
    }
  };

  // ---- back to pick ----
  const handleBack = () => {
    setStage('pick');
    setActivePlatform(null);
    setPreflight(null);
    setError(null);
    setSkipUnresolved(false);
    setFileDownloaded(null);
    setTidalResult(null);
    setSpotifyResult(null);
    setAppleMusicResult(null);
    setAppleMusicUnconfirmed(null);
    setConfirmPlaylistAbsent(false);
    setAppleMusicRecoveryResult(null);
    setDownloading(false);
  };

  // ---- derived state ----
  const hasUnresolved = (preflight?.unresolved.length ?? 0) > 0;
  // Export actions are available only when there are no unresolved OR the DJ has clicked skip
  const canExport = !hasUnresolved || skipUnresolved;

  return (
    <div className={styles.modalWrap} role="dialog" aria-modal="true">
      <div className={styles.modalBackdrop} onClick={onClose} />
      <div className={styles.importModal}>
        {/* Header */}
        <div className={styles.imHeader}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className={styles.imTitle}>
              {stage === 'pick' && 'Export Setlist'}
              {stage === 'checking' && 'Checking…'}
              {stage === 'confirm' && `Export to ${activePlatform?.label ?? ''}`}
              {stage === 'exporting' && 'Exporting…'}
              {stage === 'done' && 'Export complete'}
              {stage === 'unconfirmed' && 'Export not confirmed'}
              {stage === 'recovered' && 'Export status updated'}
            </div>
            {stage === 'pick' && (
              <div className={styles.imSubtitle}>Choose a platform or format</div>
            )}
          </div>
          <button className={styles.iconBtn} onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {/* Body */}
        <div className={styles.imBody}>
          {/* Error banner */}
          {error && <div className={styles.imError}>{error}</div>}

          {/* Stage: pick */}
          {stage === 'pick' && (
            <div className={styles.imList}>
              {PLATFORMS.map((p) => (
                <button
                  key={p.id}
                  className={styles.imListItem}
                  disabled={!p.available}
                  style={!p.available ? { opacity: 0.45, cursor: 'not-allowed' } : undefined}
                  onClick={() => handlePick(p)}
                >
                  <span className={styles.imListInfo}>
                    <span className={styles.imListTitle}>
                      {p.label}
                      {!p.available && (
                        <span
                          style={{
                            marginLeft: '0.4rem',
                            fontSize: '0.625rem',
                            padding: '0.1rem 0.4rem',
                            borderRadius: '999px',
                            background: 'var(--surface-raised, rgba(255,255,255,0.08))',
                            color: 'var(--text-secondary)',
                            fontWeight: 400,
                          }}
                        >
                          Coming soon
                        </span>
                      )}
                    </span>
                    {p.sub && <span className={styles.imListSub}>{p.sub}</span>}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Stage: checking */}
          {stage === 'checking' && (
            <div className={styles.imEmpty}>Running preflight check…</div>
          )}

          {/* Stage: confirm / exporting */}
          {(stage === 'confirm' || stage === 'exporting') && preflight && (
            <ConfirmStage
              preflight={preflight}
              platformId={activePlatform?.id ?? ''}
              skipUnresolved={skipUnresolved}
              canExport={canExport}
              fileDownloaded={fileDownloaded}
              onSkip={handleSkip}
              onCancel={handleBack}
              onTidalExport={handleTidalExport}
              onSpotifyExport={handleSpotifyExport}
              onAppleMusicExport={handleAppleMusicExport}
              onConnectSpotify={handleConnectSpotify}
              onConnectAppleMusic={handleConnectAppleMusic}
              appleMusicConnecting={appleMusicConnecting}
              onFileExport={handleFileExport}
              exporting={stage === 'exporting'}
              downloading={downloading}
            />
          )}

          {/* Stage: done (Tidal) */}
          {stage === 'done' && tidalResult && (
            <TidalDonePanel result={tidalResult} />
          )}
          {stage === 'done' && spotifyResult && <SpotifyDonePanel result={spotifyResult} />}
          {stage === 'done' && appleMusicResult && <AppleMusicDonePanel result={appleMusicResult} />}
          {stage === 'unconfirmed' && (
            <div role="status">
              <p>
                {appleMusicUnconfirmed?.message ??
                  'Apple Music did not confirm whether this playlist was created.'}
              </p>
              <p>
                Check your Apple Music library for “{set.name}”. Do not start another export
                until you have checked.
              </p>
              {appleMusicUnconfirmed?.playlistId && (
                <p>Playlist ID: {appleMusicUnconfirmed.playlistId}</p>
              )}
              <label style={{ display: 'block', marginBottom: '0.5rem' }}>
                Playlist ID
                <input
                  aria-label="Playlist ID"
                  value={recoveryPlaylistId}
                  onChange={event => setRecoveryPlaylistId(event.target.value)}
                  disabled={reconcilingAppleMusic}
                  style={{ display: 'block', width: '100%', marginTop: '0.25rem' }}
                />
              </label>
              <p style={{ fontSize: '0.6875rem', color: 'var(--text-secondary)' }}>
                Use the ID from its Apple Music link. It starts with “p.”.
              </p>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => void handleAppleMusicRecovery('playlist_found')}
                disabled={
                  reconcilingAppleMusic || !/^p\.[A-Za-z0-9_-]{1,98}$/.test(recoveryPlaylistId.trim())
                }
              >
                {reconcilingAppleMusic ? 'Saving…' : 'I found the playlist'}
              </button>
              {!confirmPlaylistAbsent ? (
                <button
                  className="btn btn-sm"
                  onClick={() => setConfirmPlaylistAbsent(true)}
                  disabled={reconcilingAppleMusic}
                  style={{ marginLeft: '0.5rem' }}
                >
                  I couldn&apos;t find the playlist
                </button>
              ) : (
                <div style={{ marginTop: '0.75rem' }}>
                  <p>Confirm that you checked your library and did not find this playlist.</p>
                  <button
                    className="btn btn-sm"
                    onClick={() => void handleAppleMusicRecovery('playlist_absent')}
                    disabled={reconcilingAppleMusic}
                  >
                    {reconcilingAppleMusic ? 'Saving…' : 'Yes, no playlist was found'}
                  </button>
                  <button
                    className="btn btn-sm"
                    onClick={() => setConfirmPlaylistAbsent(false)}
                    disabled={reconcilingAppleMusic}
                    style={{ marginLeft: '0.5rem' }}
                  >
                    Go back
                  </button>
                </div>
              )}
            </div>
          )}
          {stage === 'recovered' && appleMusicRecoveryResult && (
            <div role="status">
              <p>
                {appleMusicRecoveryResult === 'found'
                  ? 'Playlist confirmed. This set is marked as exported.'
                  : 'No playlist was found. You can start a new export when you’re ready.'}
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={styles.imFooter}>
          {stage === 'pick' && (
            <button className="btn btn-sm" onClick={onClose}>
              Close
            </button>
          )}
          {(stage === 'confirm' || stage === 'exporting' || stage === 'unconfirmed') && (
            <button
              className="btn btn-sm"
              onClick={handleBack}
              disabled={stage === 'exporting' || reconcilingAppleMusic}
            >
              ← Back
            </button>
          )}
          {(stage === 'done' || stage === 'recovered') && (
            <button className="btn btn-sm" onClick={onClose}>
              Close
            </button>
          )}
          <span style={{ flex: 1 }} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ConfirmStage sub-component
// ---------------------------------------------------------------------------

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

function ConfirmStage({
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
      {/* Summary row */}
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

      {/* Tidal not connected guidance */}
      {platformId === 'tidal' && preflight.tidal_connected === false && (
        <div className={styles.imError} style={{ borderColor: 'rgba(251,191,36,0.4)', background: 'rgba(251,191,36,0.1)', color: '#fbbf24' }}>
          Connect Tidal first — link it from your event&apos;s Cloud Providers card.
        </div>
      )}

      {platformId === 'spotify' && preflight.spotify_connected === false && (
        <div className={styles.imError} style={{ borderColor: 'rgba(251,191,36,0.4)', background: 'rgba(251,191,36,0.1)', color: '#fbbf24' }}>
          Link Spotify to create a playlist in your account.
          <button className="btn btn-sm" onClick={onConnectSpotify} style={{ display: 'block', marginTop: '0.5rem' }}>
            Connect Spotify
          </button>
        </div>
      )}

      {platformId === 'applemusic' && preflight.apple_music_connected === false && (
        <div className={styles.imError} style={{ borderColor: 'rgba(251,191,36,0.4)', background: 'rgba(251,191,36,0.1)', color: '#fbbf24' }}>
          Link Apple Music to create a playlist in your account.
          <button className="btn btn-sm" onClick={onConnectAppleMusic} disabled={appleMusicConnecting} style={{ display: 'block', marginTop: '0.5rem' }}>
            {appleMusicConnecting ? 'Connecting Apple Music…' : 'Connect Apple Music'}
          </button>
        </div>
      )}

      {/* Unresolved interrupt */}
      {preflight.unresolved.length > 0 && !skipUnresolved && (
        <UnresolvedInterrupt
          unresolved={preflight.unresolved}
          onSkip={onSkip}
          onCancel={onCancel}
        />
      )}

      {/* Export actions — only shown when canExport */}
      {canExport && platformId === 'tidal' && preflight.tidal_connected !== false && (
        <button
          className="btn btn-primary btn-sm"
          disabled={exporting}
          onClick={onTidalExport}
          style={{ marginTop: '0.5rem', width: '100%' }}
        >
          {exporting ? 'Exporting…' : 'Export to Tidal'}
        </button>
      )}

      {canExport && platformId === 'spotify' && preflight.spotify_connected !== false && (
        <button
          className="btn btn-primary btn-sm"
          disabled={exporting}
          onClick={onSpotifyExport}
          style={{ marginTop: '0.5rem', width: '100%' }}
        >
          {exporting ? 'Exporting…' : 'Export to Spotify'}
        </button>
      )}

      {canExport && platformId === 'applemusic' && preflight.apple_music_connected !== false && (
        <button
          className="btn btn-primary btn-sm"
          disabled={exporting}
          onClick={onAppleMusicExport}
          style={{ marginTop: '0.5rem', width: '100%' }}
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
            {fileDownloaded && (
              <span style={{ fontSize: '0.75rem', color: 'var(--color-success, #22c55e)', alignSelf: 'center' }}>
                Downloaded ✓
              </span>
            )}
          </div>
          {platformId !== 'rekordbox' && (
            <div
              style={{
                marginTop: '0.5rem',
                fontSize: '0.6875rem',
                color: 'var(--text-secondary)',
                lineHeight: 1.4,
              }}
            >
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
          {fileDownloaded && (
            <span style={{ fontSize: '0.75rem', color: 'var(--color-success, #22c55e)', alignSelf: 'center' }}>
              Downloaded ✓
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// UnresolvedInterrupt sub-component
// ---------------------------------------------------------------------------

interface UnresolvedInterruptProps {
  unresolved: UnresolvedTrack[];
  onSkip: () => void;
  onCancel: () => void;
}

function UnresolvedInterrupt({ unresolved, onSkip, onCancel }: UnresolvedInterruptProps) {
  return (
    <div>
      <div className={styles.imError}>
        {unresolved.length} track{unresolved.length !== 1 ? 's' : ''} couldn&apos;t be resolved
        — they will NOT be exported unless you skip them.
      </div>

      <div
        style={{
          maxHeight: '200px',
          overflowY: 'auto',
          border: '1px solid var(--border-subtle)',
          borderRadius: '8px',
          marginBottom: '0.75rem',
        }}
      >
        {unresolved.map((t) => {
          const display = t.title || t.track_id || '—';
          const artistDisplay = t.artist || '';
          return (
            <div
              key={t.position}
              style={{
                padding: '0.45rem 0.65rem',
                borderBottom: '1px solid var(--border-subtle)',
                fontSize: '0.6875rem',
              }}
            >
              <div style={{ fontWeight: 600 }}>
                {artistDisplay ? `${artistDisplay} – ${display}` : display}
              </div>
              <div style={{ color: 'var(--text-secondary)' }}>{t.reason}</div>
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

// ---------------------------------------------------------------------------
// TidalDonePanel sub-component
// ---------------------------------------------------------------------------

function TidalDonePanel({ result }: { result: ExportTidalResult }) {
  return (
    <div>
      <div
        style={{
          padding: '0.75rem',
          border: '1px solid rgba(34,197,94,0.3)',
          borderRadius: '8px',
          background: 'rgba(34,197,94,0.08)',
          marginBottom: '0.75rem',
        }}
      >
        <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '0.35rem' }}>
          Playlist created
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
          {result.added} tracks added
          {result.skipped > 0 ? `, ${result.skipped} skipped` : ''}
        </div>
      </div>

      <a
        href={result.playlist_url}
        target="_blank"
        rel="noopener noreferrer"
        className="btn btn-primary btn-sm"
        style={{ display: 'inline-block', textDecoration: 'none' }}
      >
        Open in Tidal
      </a>
    </div>
  );
}

function SpotifyDonePanel({ result }: { result: ExportSpotifyResult }) {
  return (
    <div>
      <div style={{ padding: '0.75rem', border: '1px solid rgba(34,197,94,0.3)', borderRadius: '8px', background: 'rgba(34,197,94,0.08)', marginBottom: '0.75rem' }}>
        <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '0.35rem' }}>Playlist created</div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
          {result.added} tracks added{result.skipped > 0 ? `, ${result.skipped} skipped` : ''}
        </div>
      </div>
      <a href={result.playlist_url} target="_blank" rel="noopener noreferrer" className="btn btn-primary btn-sm" style={{ display: 'inline-block', textDecoration: 'none' }}>
        Open in Spotify
      </a>
    </div>
  );
}

function AppleMusicDonePanel({ result }: { result: ExportAppleMusicResult }) {
  return (
    <div>
      <div style={{ padding: '0.75rem', border: '1px solid rgba(34,197,94,0.3)', borderRadius: '8px', background: 'rgba(34,197,94,0.08)', marginBottom: '0.75rem' }}>
        <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: '0.35rem' }}>Playlist created</div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
          {result.added} tracks added{result.skipped > 0 ? `, ${result.skipped} skipped` : ''}
        </div>
      </div>
      {result.playlist_url && (
        <a href={result.playlist_url} target="_blank" rel="noopener noreferrer" className="btn btn-primary btn-sm" style={{ display: 'inline-block', textDecoration: 'none' }}>
          Open in Apple Music
        </a>
      )}
    </div>
  );
}
