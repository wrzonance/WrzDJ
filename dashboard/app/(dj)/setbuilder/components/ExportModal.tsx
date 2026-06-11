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

import { useState } from 'react';
import { api } from '@/lib/api';
import type {
  ExportPreflight,
  ExportTarget,
  ExportFileFormat,
  ExportTidalResult,
  SetDetail,
  UnresolvedTrack,
} from '@/lib/api-types';
import styles from '../setbuilder.module.css';

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
  { id: 'enginedj' as const, label: 'Engine DJ XML', sub: '', available: false },
  { id: 'serato' as const, label: 'Serato .crate', sub: '', available: false },
  { id: 'spotify' as const, label: 'Spotify', sub: '', available: false },
  { id: 'applemusic' as const, label: 'Apple Music', sub: '', available: false },
];

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

type Stage = 'pick' | 'checking' | 'confirm' | 'exporting' | 'done';

export default function ExportModal({ set, onClose, onSetUpdated }: ExportModalProps) {
  const [stage, setStage] = useState<Stage>('pick');
  const [activePlatform, setActivePlatform] = useState<(typeof PLATFORMS)[number] | null>(null);
  const [preflight, setPreflight] = useState<ExportPreflight | null>(null);
  const [skipUnresolved, setSkipUnresolved] = useState(false);
  const [tidalResult, setTidalResult] = useState<ExportTidalResult | null>(null);
  const [fileDownloaded, setFileDownloaded] = useState<string | null>(null); // filename
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  // ---- pick a platform ----
  const handlePick = async (platform: (typeof PLATFORMS)[number]) => {
    if (!platform.available) return;
    setActivePlatform(platform);
    setError(null);
    setSkipUnresolved(false);
    setPreflight(null);
    setFileDownloaded(null);
    setStage('checking');

    const targetMap: Record<'tidal' | 'rekordbox' | 'm3u', ExportTarget> = {
      tidal: 'tidal',
      rekordbox: 'rekordbox',
      m3u: 'm3u',
    };
    const target = targetMap[platform.id as 'tidal' | 'rekordbox' | 'm3u'];

    try {
      const result = await api.exportPreflight(set.id, target);
      setPreflight(result);
      setStage('confirm');
    } catch (e) {
      setError(errMessage(e));
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

  // ---- File export (rekordbox / m3u / txt) ----
  const handleFileExport = async (format: ExportFileFormat) => {
    setError(null);
    setDownloading(true);
    const extMap: Record<ExportFileFormat, string> = {
      rekordbox: 'xml',
      m3u: 'm3u8',
      txt: 'txt',
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
              onFileExport={handleFileExport}
              exporting={stage === 'exporting'}
              downloading={downloading}
            />
          )}

          {/* Stage: done (Tidal) */}
          {stage === 'done' && tidalResult && (
            <TidalDonePanel result={tidalResult} />
          )}
        </div>

        {/* Footer */}
        <div className={styles.imFooter}>
          {stage === 'pick' && (
            <button className="btn btn-sm" onClick={onClose}>
              Close
            </button>
          )}
          {(stage === 'confirm' || stage === 'exporting') && (
            <button className="btn btn-sm" onClick={handleBack} disabled={stage === 'exporting'}>
              ← Back
            </button>
          )}
          {stage === 'done' && (
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

      {canExport && platformId === 'rekordbox' && (
        <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem' }}>
          <button
            className="btn btn-primary btn-sm"
            disabled={exporting || downloading}
            onClick={() => onFileExport('rekordbox')}
          >
            {downloading ? 'Preparing…' : 'Download .xml'}
          </button>
          {fileDownloaded && (
            <span style={{ fontSize: '0.75rem', color: 'var(--color-success, #22c55e)', alignSelf: 'center' }}>
              Downloaded ✓
            </span>
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
