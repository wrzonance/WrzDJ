'use client';

/**
 * Pool panel (issue #388) — candidate-track surface for set building.
 * Sources accordion (filter + remove-by-source), type tabs, search,
 * multi-select removal, per-track context menu, import toast.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import type {
  PoolImportResult,
  PoolSource,
  PoolState,
  SetDocumentSnapshot,
  TrackVibeState,
} from '@/lib/api-types';
import styles from '../setbuilder.module.css';
import type { ConfirmAction } from './ConfirmActionDialog';
import ImportModal, { type ImportKind } from './ImportModal';
import { BpmBadge, CamelotBadge, EnergyMini, SourceIcon, sourceColor } from './PoolBadges';
import VibeTiers from './VibeTiers';
import type { BuilderCommit } from './useSetDocumentHistory';

function buildVibeMap(tracks: TrackVibeState[]): Map<number, TrackVibeState> {
  return new Map(tracks.map((v) => [v.pool_track_id, v]));
}

const TYPE_TABS: { id: string; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'event', label: 'Requests' },
  { id: 'tidal', label: 'Tidal' },
  { id: 'beatport', label: 'Beatport' },
  { id: 'public_url', label: 'URL' },
  { id: 'manual', label: 'Manual' },
];

const IMPORT_MENU: { kind: ImportKind; title: string; sub: string }[] = [
  { kind: 'event', title: 'WrzDJ Event Requests', sub: 'Pick from your events' },
  { kind: 'tidal', title: 'Tidal Playlist', sub: 'Via your connected account' },
  { kind: 'beatport', title: 'Beatport Playlist', sub: 'Via your connected account' },
  { kind: 'public_url', title: 'Public Playlist URL', sub: 'Spotify, Tidal' },
  { kind: 'manual', title: 'Add single track', sub: 'Search a service' },
];

interface ContextMenuState {
  x: number;
  y: number;
  trackId: number;
  sourceId: number;
}

interface PoolPanelProps {
  setId: number;
  snapshot?: SetDocumentSnapshot | null;
  snapshotVersion?: number;
  commit?: BuilderCommit;
  confirmRemovals?: boolean;
  requestConfirmation?: (action: ConfirmAction) => Promise<boolean>;
}

export default function PoolPanel({
  setId,
  snapshot,
  snapshotVersion = 0,
  commit,
  confirmRemovals = false,
  requestConfirmation,
}: PoolPanelProps) {
  const [pool, setPool] = useState<PoolState>({ sources: [], tracks: [] });
  const [loaded, setLoaded] = useState(false);
  const [tab, setTab] = useState('all');
  const [q, setQ] = useState('');
  const [sourcesExpanded, setSourcesExpanded] = useState(true);
  const [activeSourceId, setActiveSourceId] = useState<number | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [importKind, setImportKind] = useState<ImportKind | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [vibes, setVibes] = useState<Map<number, TrackVibeState>>(new Map());
  const [showVibes, setShowVibes] = useState(false);
  const [vibesLoaded, setVibesLoaded] = useState(false);
  const [vibesBusy, setVibesBusy] = useState(false);

  useEffect(() => {
    setVibes(new Map());
    setShowVibes(false);
    setVibesLoaded(false);
    if (snapshot) {
      setPool(snapshot.pool);
      setLoaded(true);
      return;
    }
    api
      .getPool(setId)
      .then(setPool)
      .catch(() => setToast('Failed to load pool'))
      .finally(() => setLoaded(true));
  }, [setId, snapshot, snapshotVersion]);

  useEffect(() => {
    if (!toast) return;
    const handle = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(handle);
  }, [toast]);

  // Close popovers on outside click
  useEffect(() => {
    const onDoc = () => {
      setAddMenuOpen(false);
      setContextMenu(null);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const sourceById = useMemo(() => {
    const m = new Map<number, PoolSource>();
    for (const s of pool.sources) m.set(s.id, s);
    return m;
  }, [pool.sources]);

  const tabCounts = useMemo(() => {
    const c: Record<string, number> = { all: pool.tracks.length };
    for (const t of pool.tracks) {
      const kind = sourceById.get(t.source_id)?.kind ?? 'manual';
      c[kind] = (c[kind] ?? 0) + 1;
    }
    return c;
  }, [pool.tracks, sourceById]);

  const sourceCounts = useMemo(() => {
    const c = new Map<number, number>();
    for (const t of pool.tracks) c.set(t.source_id, (c.get(t.source_id) ?? 0) + 1);
    return c;
  }, [pool.tracks]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    return pool.tracks.filter((t) => {
      const kind = sourceById.get(t.source_id)?.kind ?? 'manual';
      if (tab !== 'all' && kind !== tab) return false;
      if (activeSourceId != null && t.source_id !== activeSourceId) return false;
      if (!term) return true;
      return `${t.title} ${t.artist} ${t.genre ?? ''}`.toLowerCase().includes(term);
    });
  }, [pool.tracks, sourceById, tab, q, activeSourceId]);

  const existingRefs = useMemo(() => {
    const refs = new Set<string>();
    for (const s of pool.sources) if (s.external_ref) refs.add(`${s.kind}:${s.external_ref}`);
    return refs;
  }, [pool.sources]);

  const onImported = useCallback((result: PoolImportResult) => {
    setPool(result.pool);
    setImportKind(null);
    setToast(`${result.added} new · ${result.deduped} de-duped`);
  }, []);

  const removeTracks = useCallback(
    async (ids: number[]) => {
      if (confirmRemovals && requestConfirmation) {
        const ok = await requestConfirmation({
          title: ids.length === 1 ? 'Remove this track?' : `Remove ${ids.length} tracks?`,
          body: 'Removing pool tracks changes the builder document and can be undone from the topbar.',
          confirmLabel: 'Remove',
          kind: 'danger',
        });
        if (!ok) return;
      }
      try {
        const save = () => api.removePoolTracks(setId, ids);
        const result = commit
          ? await commit(ids.length === 1 ? 'Remove pool track' : `Remove ${ids.length} pool tracks`, save)
          : await save();
        setPool(result.pool);
        setSelected(new Set());
        setSelectMode(false);
        setToast(`Removed ${result.removed} track${result.removed === 1 ? '' : 's'}`);
      } catch {
        setToast('Remove failed');
      }
    },
    [commit, confirmRemovals, requestConfirmation, setId],
  );

  const removeSource = useCallback(
    async (sourceId: number) => {
      const source = pool.sources.find((s) => s.id === sourceId);
      if (confirmRemovals && requestConfirmation) {
        const ok = await requestConfirmation({
          title: `Remove source${source ? ` ${source.label}` : ''}?`,
          body:
            'Removing a source removes its imported tracks from the builder document and can be undone from the topbar.',
          confirmLabel: 'Remove source',
          kind: 'danger',
        });
        if (!ok) return;
      }
      try {
        const save = () => api.removePoolSource(setId, sourceId);
        const result = commit
          ? await commit(`Remove source${source ? ` ${source.label}` : ''}`, save)
          : await save();
        setPool(result.pool);
        if (activeSourceId === sourceId) setActiveSourceId(null);
        setToast(`Removed source · ${result.removed} tracks`);
      } catch {
        setToast('Remove failed');
      }
    },
    [activeSourceId, commit, confirmRemovals, pool.sources, requestConfirmation, setId],
  );

  const toggleVibes = useCallback(() => {
    if (!showVibes && !vibesLoaded && !vibesBusy) {
      // vibesBusy also disables Analyze while this first fetch is in flight,
      // so an Analyze response can't be overwritten by a stale initial GET.
      // vibesLoaded is only set on success so a failed fetch can be retried.
      setVibesBusy(true);
      api
        .getPoolVibes(setId)
        .then((result) => {
          setVibes(buildVibeMap(result.tracks));
          setVibesLoaded(true);
        })
        .catch(() => setToast('Failed to load vibes'))
        .finally(() => setVibesBusy(false));
    }
    setShowVibes((s) => !s);
  }, [showVibes, vibesLoaded, vibesBusy, setId]);

  const analyzeVibes = useCallback(async () => {
    setVibesBusy(true);
    try {
      const result = await api.enrichPoolVibes(setId);
      setVibes(buildVibeMap(result.vibes.tracks));
      setToast(`${result.enriched} analyzed · ${result.cached} cached · ${result.failed} failed`);
    } catch (err) {
      setToast(err instanceof ApiError && err.status === 400 ? err.message : 'Vibe analysis failed');
    } finally {
      setVibesBusy(false);
    }
  }, [setId]);

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className={styles.poolPanel}>
      {/* Header: count + Add menu */}
      <div className={styles.poolHeader}>
        <span className={styles.poolTitle}>
          Pool <span className={styles.poolCount}>{pool.tracks.length}</span>
        </span>
        <span style={{ flex: 1 }} />
        {showVibes && (
          <button
            className="btn btn-sm"
            onClick={analyzeVibes}
            disabled={vibesBusy}
            title="Analyze uncached pool tracks with AI"
          >
            {vibesBusy ? 'Analyzing…' : 'Analyze'}
          </button>
        )}
        <button
          className="btn btn-sm"
          onClick={toggleVibes}
          aria-pressed={showVibes}
          title="Show three-tier vibe state per track"
        >
          Vibes
        </button>
        <span style={{ position: 'relative' }} onMouseDown={(e) => e.stopPropagation()}>
          <button
            className="btn btn-sm"
            onClick={() => setAddMenuOpen((o) => !o)}
            aria-expanded={addMenuOpen}
          >
            + Add
          </button>
          {addMenuOpen && (
            <div className={styles.popoverMenu}>
              <div className={styles.popoverLabel}>Import from</div>
              {IMPORT_MENU.map((m) => (
                <button
                  key={m.kind}
                  className={styles.popoverItem}
                  onClick={() => {
                    setAddMenuOpen(false);
                    setImportKind(m.kind);
                  }}
                >
                  <span style={{ color: sourceColor(m.kind) }}>
                    <SourceIcon kind={m.kind} />
                  </span>
                  <span>
                    <span className={styles.popoverItemTitle}>{m.title}</span>
                    <span className={styles.popoverItemSub}>{m.sub}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </span>
      </div>

      {/* Sources accordion */}
      <div className={styles.poolSources}>
        <button className={styles.sourcesToggle} onClick={() => setSourcesExpanded((e) => !e)}>
          <span className={styles.sourcesCaret}>{sourcesExpanded ? '▾' : '▸'}</span>
          <span>Sources</span>
          <span className={styles.poolCount}>{pool.sources.length}</span>
          <span style={{ flex: 1 }} />
          {activeSourceId != null && (
            <span
              role="button"
              tabIndex={0}
              className={styles.sourcesClearFilter}
              onClick={(e) => {
                e.stopPropagation();
                setActiveSourceId(null);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') setActiveSourceId(null);
              }}
            >
              filtered · clear
            </span>
          )}
        </button>
        {sourcesExpanded && (
          <div>
            {pool.sources.map((s) => {
              const count = sourceCounts.get(s.id) ?? 0;
              const isActive = activeSourceId === s.id;
              return (
                <div key={s.id} className={`${styles.sourceRow} ${isActive ? styles.sourceRowActive : ''}`}>
                  <button
                    className={styles.sourceRowMain}
                    onClick={() => setActiveSourceId(isActive ? null : s.id)}
                    title="Click to filter pool by this source"
                  >
                    <span style={{ color: sourceColor(s.kind) }}>
                      <SourceIcon kind={s.kind} size={13} />
                    </span>
                    <span className={styles.sourceInfo}>
                      <span className={styles.sourceLabel}>{s.label}</span>
                      {s.meta && <span className={styles.sourceMeta}>{s.meta}</span>}
                    </span>
                    <span className={styles.sourceCount}>{count}</span>
                  </button>
                  {s.kind !== 'manual' && (
                    <button
                      className={styles.sourceRemove}
                      onClick={() => removeSource(s.id)}
                      title={`Remove all ${count} tracks imported via "${s.label}"`}
                      aria-label={`Remove source ${s.label}`}
                    >
                      ✕
                    </button>
                  )}
                </div>
              );
            })}
            {loaded && pool.sources.length === 0 && (
              <div className={styles.sourcesEmpty}>
                No sources yet. Tap <strong>+ Add</strong> to import.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Type tabs */}
      <div className={styles.poolTabs}>
        {TYPE_TABS.map((t) => (
          <button
            key={t.id}
            className={`${styles.poolTab} ${tab === t.id ? styles.poolTabActive : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label} <span className={styles.poolCount}>{tabCounts[t.id] ?? 0}</span>
          </button>
        ))}
      </div>

      {/* Search + multi-select toggle */}
      <div className={styles.poolSearch}>
        <input
          className={styles.imInput}
          placeholder="Search pool…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ flex: 1 }}
        />
        <button
          className="btn btn-sm"
          onClick={() => {
            setSelectMode((m) => !m);
            setSelected(new Set());
          }}
          title={selectMode ? 'Exit multi-select' : 'Multi-select tracks'}
          aria-pressed={selectMode}
        >
          ☑
        </button>
      </div>

      {/* Track list */}
      <div className={styles.poolList}>
        {filtered.map((t) => {
          const source = sourceById.get(t.source_id);
          const isSelected = selected.has(t.id);
          const vibe = showVibes ? vibes.get(t.id) : undefined;
          return (
            <div
              key={t.id}
              className={`${styles.poolTrack} ${isSelected ? styles.poolTrackSelected : ''}`}
              onClick={() => selectMode && toggleSelect(t.id)}
              onContextMenu={(e) => {
                e.preventDefault();
                setContextMenu({ x: e.clientX, y: e.clientY, trackId: t.id, sourceId: t.source_id });
              }}
            >
              {selectMode && (
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => toggleSelect(t.id)}
                  onClick={(e) => e.stopPropagation()}
                  aria-label={`Select ${t.title}`}
                />
              )}
              <div className={styles.trackInfo}>
                <div className={styles.trackTitle}>{t.title}</div>
                <div className={styles.trackArtist}>{t.artist}</div>
                <div className={styles.trackMetaRow}>
                  <BpmBadge bpm={t.bpm} />
                  <CamelotBadge camelot={t.camelot} />
                  <EnergyMini value={t.energy} />
                  {source && (
                    <span
                      className={styles.srcChip}
                      style={{ color: sourceColor(source.kind) }}
                      title={`Imported via ${source.label}`}
                    >
                      <SourceIcon kind={source.kind} size={10} />
                      <span className={styles.srcChipLabel}>
                        {source.label.length > 18 ? `${source.label.slice(0, 16)}…` : source.label}
                      </span>
                    </span>
                  )}
                </div>
                {vibe && <VibeTiers state={vibe} />}
              </div>
              <div
                className={styles.poolTrackStripe}
                style={{ background: sourceColor(source?.kind) }}
              />
            </div>
          );
        })}
        {loaded && filtered.length === 0 && (
          <div className={styles.imEmpty}>
            {pool.tracks.length === 0 ? 'Pool is empty — import some tracks.' : 'No matches.'}
          </div>
        )}
      </div>

      {/* Multi-select footer */}
      {selectMode && (
        <div className={styles.selectFooter}>
          <button
            className="btn btn-sm"
            onClick={() => setSelected(new Set(filtered.map((t) => t.id)))}
          >
            Select all visible
          </button>
          <button className="btn btn-sm" onClick={() => setSelected(new Set())} disabled={!selected.size}>
            Clear
          </button>
          <span style={{ flex: 1 }} />
          <button
            className={`btn btn-sm ${styles.dangerBtn}`}
            disabled={!selected.size}
            onClick={() => removeTracks([...selected])}
          >
            Remove {selected.size || ''}
          </button>
          <button
            className="btn btn-sm"
            onClick={() => {
              setSelectMode(false);
              setSelected(new Set());
            }}
          >
            Done
          </button>
        </div>
      )}

      {/* Context menu */}
      {contextMenu && (
        <div
          className={styles.popoverMenu}
          style={{ position: 'fixed', left: contextMenu.x, top: contextMenu.y, right: 'auto' }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <button
            className={styles.popoverItem}
            onClick={() => {
              removeTracks([contextMenu.trackId]);
              setContextMenu(null);
            }}
          >
            <span className={styles.popoverItemTitle}>Remove this track</span>
          </button>
          {(() => {
            const source = sourceById.get(contextMenu.sourceId);
            if (!source || source.kind === 'manual') return null;
            const count = sourceCounts.get(source.id) ?? 0;
            return (
              <button
                className={styles.popoverItem}
                onClick={() => {
                  removeSource(source.id);
                  setContextMenu(null);
                }}
              >
                <span>
                  <span className={styles.popoverItemTitle}>
                    Remove all from “{source.label}”
                  </span>
                  <span className={styles.popoverItemSub}>{count} tracks</span>
                </span>
              </button>
            );
          })()}
          <button
            className={styles.popoverItem}
            onClick={() => {
              setSelectMode(true);
              setSelected(new Set([contextMenu.trackId]));
              setContextMenu(null);
            }}
          >
            <span className={styles.popoverItemTitle}>Multi-select…</span>
          </button>
        </div>
      )}

      {/* Import modal */}
      {importKind && (
        <ImportModal
          kind={importKind}
          setId={setId}
          existingRefs={existingRefs}
          onClose={() => setImportKind(null)}
          onImported={onImported}
          onError={(msg) => setToast(msg)}
          commit={commit}
        />
      )}

      {/* Toast */}
      {toast && (
        <div className={styles.poolToast} role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
