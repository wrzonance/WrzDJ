'use client';

import { useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api';
import type { Pairing, PoolTrack } from '@/lib/api-types';
import type { CSSProperties } from 'react';
import {
  BPM_TIER_COLORS,
  KEY_TIER_COLORS,
  bpmPercentDelta,
  camelotMixTier,
  fmtTime,
} from './curveMath';
import type { SlotView } from './types';
import { slotViewFromApi } from './types';
import styles from '../setbuilder.module.css';

const EMPTY_STATE = { count: 0, pairings: [] as Pairing[] };

interface PairingsOverlayProps {
  setId: number;
  open: boolean;
  initialPairingId: number | null;
  onClose: () => void;
  onChanged: (count: number) => void;
  onJumpSlot: (idx: number) => void;
}

function initials(track: PoolTrack | null | undefined): string {
  const artist = track?.artist || track?.title || '?';
  return artist
    .split(/[,\s]+/)
    .filter(Boolean)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

function artStyle(trackId: string | null | undefined): CSSProperties {
  const seed = [...(trackId ?? 'manual')].reduce((acc, c) => acc + c.charCodeAt(0), 0);
  const h1 = (seed * 37) % 360;
  const h2 = (h1 + 70) % 360;
  return { background: `linear-gradient(135deg, hsl(${h1} 58% 35%), hsl(${h2} 54% 24%))` };
}

function pairingMatches(pairing: Pairing, q: string): boolean {
  if (!q) return true;
  const hay = [
    pairing.from_track?.title,
    pairing.from_track?.artist,
    pairing.into_track?.title,
    pairing.into_track?.artist,
    pairing.from_track_id,
    pairing.into_track_id,
    pairing.note,
    ...(pairing.tags ?? []),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return hay.includes(q.toLowerCase());
}

function TrackArt({ track }: { track: PoolTrack | null | undefined }) {
  return (
    <span className={styles.pairingArt} style={artStyle(track?.track_id)}>
      {initials(track)}
    </span>
  );
}

function LinkIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M10.5 13.5 13.5 10.5M8.5 17.5H7.8a4.8 4.8 0 0 1 0-9.6h3.4M12.8 16.1h3.4a4.8 4.8 0 1 0 0-9.6h-.7"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function PairingMini({ pairing }: { pairing: Pairing }) {
  return (
    <div className={styles.pairingMini}>
      <div className={styles.pairingMiniTrack}>
        <TrackArt track={pairing.from_track} />
        <span className={styles.pairingMiniInfo}>
          <span className={styles.pairingMiniTitle}>
            {pairing.from_track?.title ?? pairing.from_track_id}
          </span>
          <span className={styles.pairingMiniArtist}>{pairing.from_track?.artist ?? 'Unknown'}</span>
        </span>
      </div>
      <span className={styles.pairingArrow}>-&gt;</span>
      <div className={styles.pairingMiniTrack}>
        <TrackArt track={pairing.into_track} />
        <span className={styles.pairingMiniInfo}>
          <span className={styles.pairingMiniTitle}>
            {pairing.into_track?.title ?? pairing.into_track_id}
          </span>
          <span className={styles.pairingMiniArtist}>{pairing.into_track?.artist ?? 'Unknown'}</span>
        </span>
      </div>
    </div>
  );
}

function CompatibilityChips({ from, into }: { from?: PoolTrack | null; into?: PoolTrack | null }) {
  const bpm = bpmPercentDelta(from?.bpm ?? null, into?.bpm ?? null);
  const key = camelotMixTier(from?.camelot ?? from?.key ?? null, into?.camelot ?? into?.key ?? null);
  const bpmColor = BPM_TIER_COLORS[bpm.tier];
  const keyColor = KEY_TIER_COLORS[key.tier];
  return (
    <>
      <span className={styles.pairingMetricChip} style={{ color: bpmColor.chip, background: bpmColor.chipBg }}>
        {bpm.pct == null ? '? BPM' : `${bpm.pct.toFixed(1)}% BPM`}
      </span>
      <span className={styles.pairingMetricChip} style={{ color: keyColor.chip, background: keyColor.chipBg }}>
        {key.label}
      </span>
    </>
  );
}

function PairingDetail({
  pairing,
  slots,
  onUpdate,
  onDelete,
  onJump,
}: {
  pairing: Pairing;
  slots: SlotView[];
  onUpdate: (patch: { note?: string; cue_in_sec?: number | null; tags?: string[] }) => Promise<void>;
  onDelete: () => Promise<void>;
  onJump: (idx: number) => void;
}) {
  const [editingNote, setEditingNote] = useState(false);
  const [note, setNote] = useState(pairing.note ?? '');

  useEffect(() => {
    setNote(pairing.note ?? '');
    setEditingNote(false);
  }, [pairing.id, pairing.note]);

  const useInSet = useMemo(() => {
    for (let i = 0; i < slots.length - 1; i += 1) {
      if (
        slots[i].track.id === pairing.from_track_id &&
        slots[i + 1].track.id === pairing.into_track_id
      ) {
        return i;
      }
    }
    return null;
  }, [slots, pairing.from_track_id, pairing.into_track_id]);

  const bpm = bpmPercentDelta(pairing.from_track?.bpm ?? null, pairing.into_track?.bpm ?? null);
  const key = camelotMixTier(
    pairing.from_track?.camelot ?? pairing.from_track?.key ?? null,
    pairing.into_track?.camelot ?? pairing.into_track?.key ?? null,
  );

  return (
    <div className={styles.pairingDetail}>
      <div className={styles.pairingHero}>
        <div className={styles.pairingHeroTrack}>
          <span className={styles.pairingRole}>FROM</span>
          <TrackArt track={pairing.from_track} />
          <strong>{pairing.from_track?.title ?? pairing.from_track_id}</strong>
          <span>{pairing.from_track?.artist ?? 'Unknown artist'}</span>
        </div>
        <div className={styles.pairingHeroArrow}>
          <span>-&gt;</span>
          {pairing.cue_in_sec != null && pairing.cue_in_sec > 0 && (
            <span className={styles.pairingCue}>cue @ {fmtTime(pairing.cue_in_sec)}</span>
          )}
        </div>
        <div className={styles.pairingHeroTrack}>
          <span className={styles.pairingRole}>INTO</span>
          <TrackArt track={pairing.into_track} />
          <strong>{pairing.into_track?.title ?? pairing.into_track_id}</strong>
          <span>{pairing.into_track?.artist ?? 'Unknown artist'}</span>
        </div>
      </div>

      <div className={styles.pairingStatsGrid}>
        <div className={styles.pairingStatCard} style={{ borderColor: BPM_TIER_COLORS[bpm.tier].stroke }}>
          <span>BPM delta</span>
          <strong style={{ color: BPM_TIER_COLORS[bpm.tier].chip }}>
            {bpm.pct == null ? '?' : `${bpm.pct.toFixed(1)}%`}
          </strong>
          <small>{pairing.from_track?.bpm ?? '-'} -&gt; {pairing.into_track?.bpm ?? '-'}</small>
        </div>
        <div className={styles.pairingStatCard} style={{ borderColor: KEY_TIER_COLORS[key.tier].stroke }}>
          <span>Camelot</span>
          <strong style={{ color: KEY_TIER_COLORS[key.tier].chip }}>{key.label}</strong>
          <small>{pairing.from_track?.camelot ?? '-'} -&gt; {pairing.into_track?.camelot ?? '-'}</small>
        </div>
        <div className={styles.pairingStatCard}>
          <span>Energy</span>
          <strong>
            {pairing.from_track?.energy ?? '-'} -&gt; {pairing.into_track?.energy ?? '-'}
          </strong>
          <small>slot vibe signal</small>
        </div>
        <div className={styles.pairingStatCard}>
          <span>Uses</span>
          <strong>{pairing.use_count}</strong>
          <small>captured transitions</small>
        </div>
      </div>

      <section className={styles.pairingSection}>
        <div className={styles.pairingSectionHead}>
          <span>DJ note</span>
          {!editingNote && (
            <button type="button" className="btn btn-sm" onClick={() => setEditingNote(true)}>
              Edit
            </button>
          )}
        </div>
        {editingNote ? (
          <>
            <textarea
              className={styles.pairingTextarea}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={4}
              autoFocus
            />
            <div className={styles.pairingInlineActions}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={async () => {
                  try {
                    await onUpdate({ note });
                    setEditingNote(false);
                  } catch {
                    // The parent owns user-visible mutation errors.
                  }
                }}
              >
                Save
              </button>
              <button type="button" className="btn btn-sm" onClick={() => setEditingNote(false)}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <p className={styles.pairingNote}>
            {pairing.note || 'No note yet. Add cue, mixer, or crowd-read context.'}
          </p>
        )}
      </section>

      <div className={styles.pairingTags}>
        {(pairing.tags ?? []).map((tag) => (
          <span key={tag}>#{tag}</span>
        ))}
      </div>

      <div className={styles.pairingSetUse}>
        {useInSet == null ? (
          <span>This transition is not adjacent in the current set.</span>
        ) : (
          <>
            <span>Currently in this set: slot {String(useInSet + 1).padStart(2, '0')} -&gt; {String(useInSet + 2).padStart(2, '0')}</span>
            <button type="button" className="btn btn-sm" onClick={() => onJump(useInSet)}>
              Jump
            </button>
          </>
        )}
      </div>

      <div className={styles.pairingFooter}>
        <button
          type="button"
          className={`btn btn-sm ${styles.dangerBtn}`}
          onClick={() => {
            void onDelete().catch(() => {});
          }}
        >
          Delete pairing
        </button>
      </div>
    </div>
  );
}

function TrackPicker({
  label,
  pool,
  selected,
  excludeTrackId,
  onSelect,
}: {
  label: string;
  pool: PoolTrack[];
  selected: PoolTrack | null;
  excludeTrackId: string | null;
  onSelect: (track: PoolTrack | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const results = pool
    .filter((track) => track.track_id && track.track_id !== excludeTrackId)
    .filter((track) => `${track.title} ${track.artist}`.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 30);

  return (
    <div className={styles.pairingPicker}>
      <span className={styles.pairingRole}>{label}</span>
      {selected ? (
        <div className={styles.pairingPickerSelected}>
          <TrackArt track={selected} />
          <span>
            <strong>{selected.title}</strong>
            <small>{selected.artist}</small>
          </span>
          <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>
            Change
          </button>
        </div>
      ) : (
        <button type="button" className={styles.pairingPickerEmpty} onClick={() => setOpen(true)}>
          Pick a track
        </button>
      )}
      {open && (
        <div className={styles.pairingPickerPopover}>
          <input
            className={styles.imInput}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search pool..."
            autoFocus
          />
          <div className={styles.pairingPickerResults}>
            {results.map((track) => (
              <button
                key={track.id}
                type="button"
                className={styles.pairingPickerResult}
                onClick={() => {
                  onSelect(track);
                  setOpen(false);
                  setQ('');
                }}
              >
                <TrackArt track={track} />
                <span>
                  <strong>{track.title}</strong>
                  <small>{track.artist} · {track.bpm ?? '-'} BPM · {track.camelot ?? track.key ?? '-'}</small>
                </span>
              </button>
            ))}
            {results.length === 0 && <div className={styles.pairingPickerNone}>No tracks found.</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function PairingAddForm({
  pool,
  pairings,
  onCancel,
  onSave,
}: {
  pool: PoolTrack[];
  pairings: Pairing[];
  onCancel: () => void;
  onSave: (payload: { from_track_id: string; into_track_id: string; cue_in_sec: number | null; note: string | null; tags: string[] }) => Promise<void>;
}) {
  const [from, setFrom] = useState<PoolTrack | null>(null);
  const [into, setInto] = useState<PoolTrack | null>(null);
  const [note, setNote] = useState('');
  const [cue, setCue] = useState('');
  const [tagText, setTagText] = useState('');

  const tags = useMemo(
    () => tagText.split(',').map((tag) => tag.trim().replace(/^#/, '')).filter(Boolean),
    [tagText],
  );
  const duplicate = Boolean(
    from?.track_id &&
      into?.track_id &&
      pairings.some((p) => p.from_track_id === from.track_id && p.into_track_id === into.track_id),
  );
  const canSave = Boolean(from?.track_id && into?.track_id && !duplicate);

  return (
    <div className={styles.pairingAdd}>
      <h3>New pairing</h3>
      <p>Capture a directional transition you know works. It will be weighted into pass-1 scoring.</p>
      <div className={styles.pairingAddFlow}>
        <TrackPicker
          label="FROM"
          pool={pool}
          selected={from}
          excludeTrackId={into?.track_id ?? null}
          onSelect={setFrom}
        />
        <span className={styles.pairingHeroArrow}>-&gt;</span>
        <TrackPicker
          label="INTO"
          pool={pool}
          selected={into}
          excludeTrackId={from?.track_id ?? null}
          onSelect={setInto}
        />
      </div>
      {duplicate && from && into && (
        <div className={styles.pairingWarn}>
          A pairing already exists for {from.title} -&gt; {into.title}.
        </div>
      )}
      {from && into && !duplicate && (
        <div className={styles.pairingPreview}>
          <CompatibilityChips from={from} into={into} />
          <span className={styles.pairingMetricChip}>E {from.energy ?? '-'} -&gt; {into.energy ?? '-'}</span>
        </div>
      )}
      <label className={styles.pairingField}>
        <span>Note</span>
        <textarea
          className={styles.pairingTextarea}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          placeholder="Cue point, mixer move, vibe read..."
        />
      </label>
      <div className={styles.pairingAddGrid}>
        <label className={styles.pairingField}>
          <span>Cue in seconds</span>
          <input className={styles.imInput} value={cue} onChange={(e) => setCue(e.target.value)} inputMode="numeric" />
        </label>
        <label className={styles.pairingField}>
          <span>Tags</span>
          <input className={styles.imInput} value={tagText} onChange={(e) => setTagText(e.target.value)} placeholder="wedding, safe, peak" />
        </label>
      </div>
      <div className={styles.pairingFooter}>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!canSave}
          onClick={async () => {
            if (!from?.track_id || !into?.track_id) return;
            try {
              await onSave({
                from_track_id: from.track_id,
                into_track_id: into.track_id,
                cue_in_sec: cue.trim() ? Math.max(0, Number.parseInt(cue, 10) || 0) : null,
                note: note.trim() || null,
                tags,
              });
            } catch {
              // The parent owns user-visible mutation errors.
            }
          }}
        >
          Save pairing
        </button>
      </div>
    </div>
  );
}

export default function PairingsOverlay({
  setId,
  open,
  initialPairingId,
  onClose,
  onChanged,
  onJumpSlot,
}: PairingsOverlayProps) {
  const [state, setState] = useState(EMPTY_STATE);
  const [pool, setPool] = useState<PoolTrack[]>([]);
  const [slots, setSlots] = useState<SlotView[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mode, setMode] = useState<'view' | 'add'>('view');
  const [filter, setFilter] = useState('');
  const [error, setError] = useState<string | null>(null);

  const notifyChanged = (count: number) => {
    onChanged(count);
    window.dispatchEvent(
      new CustomEvent('wrzdj:setbuilder-pairings-changed', { detail: { count } }),
    );
  };

  const reload = async () => {
    const [pairings, poolState, slotRows] = await Promise.all([
      api.getPairings(setId),
      api.getPool(setId),
      api.getSetSlots(setId),
    ]);
    const poolByTrackId = new Map(
      poolState.tracks
        .filter((track) => track.track_id)
        .map((track) => [track.track_id as string, track]),
    );
    setState(pairings);
    setPool(poolState.tracks);
    setSlots(slotRows.map((slot) => slotViewFromApi(slot, poolByTrackId.get(slot.track_id ?? '') ?? null)));
    onChanged(pairings.count);
    if (initialPairingId) setSelectedId(initialPairingId);
    else if (!selectedId && pairings.pairings.length > 0) setSelectedId(pairings.pairings[0].id);
    if (pairings.pairings.length === 0) setMode('add');
  };

  useEffect(() => {
    if (!open) return;
    setFilter('');
    setError(null);
    reload().catch(() => setError('Pairings failed to load.'));
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, setId, initialPairingId]);

  if (!open) return null;

  const pairings = state.pairings;
  const filtered = pairings.filter((pairing) => pairingMatches(pairing, filter));
  const selected = pairings.find((pairing) => pairing.id === selectedId) ?? null;
  const totalUses = pairings.reduce((sum, pairing) => sum + pairing.use_count, 0);

  return (
    <div className={styles.pairingsWrap}>
      <button type="button" className={styles.pairingsBackdrop} aria-label="Close pairings" onClick={onClose} />
      <div className={styles.pairingsShell} role="dialog" aria-label="Pairings">
        <header className={styles.pairingsHeader}>
          <div className={styles.pairingsIcon}>
            <LinkIcon />
          </div>
          <div className={styles.pairingsHeaderText}>
            <h2>Pairings</h2>
            <p>DJ-curated transitions weighted into pass-1 scoring.</p>
          </div>
          <div className={styles.pairingsStats}>
            <span><strong>{pairings.length}</strong> saved</span>
            <span><strong>{totalUses}</strong> uses</span>
          </div>
          <button type="button" className={styles.iconBtn} onClick={onClose} aria-label="Close">
            x
          </button>
        </header>
        <div className={styles.pairingsBody}>
          <aside className={styles.pairingsListCol}>
            <div className={styles.pairingsToolbar}>
              <input
                className={styles.imInput}
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search saved pairings..."
              />
              <button type="button" className="btn btn-sm" onClick={() => { setMode('add'); setSelectedId(null); }}>
                New
              </button>
            </div>
            <div className={styles.pairingsList}>
              {error && <div className={styles.imError}>{error}</div>}
              {filtered.map((pairing) => (
                <button
                  key={pairing.id}
                  type="button"
                  className={`${styles.pairingCard} ${selectedId === pairing.id ? styles.pairingCardActive : ''}`}
                  onClick={() => { setSelectedId(pairing.id); setMode('view'); }}
                >
                  <PairingMini pairing={pairing} />
                  <div className={styles.pairingCardTags}>
                    <CompatibilityChips from={pairing.from_track} into={pairing.into_track} />
                    <span className={styles.pairingUses}>x{pairing.use_count}</span>
                  </div>
                </button>
              ))}
              {!error && filtered.length === 0 && (
                <div className={styles.pairingsEmpty}>
                  {pairings.length === 0 ? 'No pairings yet.' : 'No pairings match that search.'}
                </div>
              )}
            </div>
          </aside>
          <main className={styles.pairingsDetailCol}>
            {mode === 'add' ? (
              <PairingAddForm
                pool={pool}
                pairings={pairings}
                onCancel={() => setMode('view')}
                onSave={async (payload) => {
                  try {
                    setError(null);
                    const saved = await api.savePairing(setId, {
                      ...payload,
                      increment_use_count: false,
                    });
                    await reload();
                    setSelectedId(saved.id);
                    setMode('view');
                    notifyChanged(state.count + 1);
                  } catch (err) {
                    setError('Failed to save pairing.');
                    throw err;
                  }
                }}
              />
            ) : selected ? (
              <PairingDetail
                pairing={selected}
                slots={slots}
                onUpdate={async (patch) => {
                  try {
                    setError(null);
                    await api.updatePairing(setId, selected.id, patch);
                    await reload();
                    notifyChanged(state.count);
                  } catch (err) {
                    setError('Failed to update pairing.');
                    throw err;
                  }
                }}
                onDelete={async () => {
                  try {
                    setError(null);
                    await api.deletePairing(setId, selected.id);
                    await reload();
                    setSelectedId(null);
                    notifyChanged(Math.max(0, state.count - 1));
                  } catch (err) {
                    setError('Failed to delete pairing.');
                    throw err;
                  }
                }}
                onJump={(idx) => {
                  onJumpSlot(idx);
                  onClose();
                }}
              />
            ) : (
              <div className={styles.pairingsEmpty}>Pick a pairing or create a new one.</div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
