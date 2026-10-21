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
  SetDetail,
} from '@/lib/api/types';

import sharedStyles from '../setbuilder-shared.module.css';
import importStyles from '../setbuilder-import.module.css';
import { authorizeAppleMusic } from '@/lib/apple-music-auth';
import {
  AppleMusicDonePanel,
  ConfirmStage,
  SpotifyDonePanel,
  TidalDonePanel,
} from './ExportModalPanels';
import { AppleMusicRecoveryPanel } from './AppleMusicRecoveryPanel';
import { useAppleMusicRecovery } from './useAppleMusicRecovery';

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
  const [fileDownloaded, setFileDownloaded] = useState<string | null>(null); // filename
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [appleMusicConnecting, setAppleMusicConnecting] = useState(false);
  const appleMusicConnectInFlight = useRef(false);
  const appleMusicRecovery = useAppleMusicRecovery({
    set,
    onSetUpdated,
    onRecovered: () => setStage('recovered'),
  });

  // ---- pick a platform ----
  const handlePick = async (platform: (typeof PLATFORMS)[number]) => {
    if (!platform.available) return;
    setActivePlatform(platform);
    setError(null);
    setSkipUnresolved(false);
    setPreflight(null);
    appleMusicRecovery.reset();
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
        appleMusicRecovery.begin({ message: e.message, playlistId });
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
    appleMusicRecovery.reset();
    setDownloading(false);
  };

  // ---- derived state ----
  const hasUnresolved = (preflight?.unresolved.length ?? 0) > 0;
  // Export actions are available only when there are no unresolved OR the DJ has clicked skip
  const canExport = !hasUnresolved || skipUnresolved;

  return (
    <div className={sharedStyles.modalWrap} role="dialog" aria-modal="true">
      <div className={sharedStyles.modalBackdrop} onClick={onClose} />
      <div className={importStyles.importModal}>
        {/* Header */}
        <div className={importStyles.imHeader}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className={importStyles.imTitle}>
              {stage === 'pick' && 'Export Setlist'}
              {stage === 'checking' && 'Checking…'}
              {stage === 'confirm' && `Export to ${activePlatform?.label ?? ''}`}
              {stage === 'exporting' && 'Exporting…'}
              {stage === 'done' && 'Export complete'}
              {stage === 'unconfirmed' && 'Export not confirmed'}
              {stage === 'recovered' && 'Export status updated'}
            </div>
            {stage === 'pick' && (
              <div className={importStyles.imSubtitle}>Choose a platform or format</div>
            )}
          </div>
          <button className={sharedStyles.iconBtn} onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {/* Body */}
        <div className={importStyles.imBody}>
          {/* Error banner */}
          {error && <div className={sharedStyles.imError}>{error}</div>}

          {/* Stage: pick */}
          {stage === 'pick' && (
            <div className={importStyles.imList}>
              {PLATFORMS.map((p) => (
                <button
                  key={p.id}
                  className={importStyles.imListItem}
                  disabled={!p.available}
                  style={!p.available ? { opacity: 0.45, cursor: 'not-allowed' } : undefined}
                  onClick={() => handlePick(p)}
                >
                  <span className={importStyles.imListInfo}>
                    <span className={importStyles.imListTitle}>
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
                    {p.sub && <span className={importStyles.imListSub}>{p.sub}</span>}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Stage: checking */}
          {stage === 'checking' && (
            <div className={sharedStyles.imEmpty}>Running preflight check…</div>
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
          {(stage === 'unconfirmed' || stage === 'recovered') && (
            <AppleMusicRecoveryPanel
              setName={set.name}
              unconfirmed={appleMusicRecovery.unconfirmed}
              playlistId={appleMusicRecovery.playlistId}
              onPlaylistIdChange={appleMusicRecovery.setPlaylistId}
              confirmPlaylistAbsent={appleMusicRecovery.confirmPlaylistAbsent}
              onConfirmPlaylistAbsentChange={appleMusicRecovery.setConfirmPlaylistAbsent}
              isReconciling={appleMusicRecovery.isReconciling}
              result={appleMusicRecovery.result}
              error={appleMusicRecovery.error}
              onRecover={action => void appleMusicRecovery.reconcile(action)}
            />
          )}
        </div>

        {/* Footer */}
        <div className={importStyles.imFooter}>
          {stage === 'pick' && (
            <button className="btn btn-sm" onClick={onClose}>
              Close
            </button>
          )}
          {(stage === 'confirm' || stage === 'exporting' || stage === 'unconfirmed') && (
            <button
              className="btn btn-sm"
              onClick={handleBack}
              disabled={stage === 'exporting' || appleMusicRecovery.isReconciling}
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
