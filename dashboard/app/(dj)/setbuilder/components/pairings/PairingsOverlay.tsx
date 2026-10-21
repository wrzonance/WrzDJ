'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Pairing, PoolTrack } from '@/lib/api/types';
import type { SlotView } from '../types';
import { PairingAddForm } from './PairingAddForm';
import { PairingDetail } from './PairingDetail';
import { CompatibilityChips, LinkIcon, PairingMini, pairingMatches } from './PairingVisuals';

import pairingStyles from '../../setbuilder-pairings.module.css';
import sharedStyles from '../../setbuilder-shared.module.css';
import { slotViewFromApi } from '../types';

const EMPTY_STATE = { count: 0, pairings: [] as Pairing[] };

interface PairingsOverlayProps {
  setId: number;
  open: boolean;
  initialPairingId: number | null;
  onClose: () => void;
  onChanged: (count: number) => void;
  onJumpSlot: (idx: number) => void;
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
    <div className={pairingStyles.pairingsWrap}>
      <button type="button" className={pairingStyles.pairingsBackdrop} aria-label="Close pairings" onClick={onClose} />
      <div className={pairingStyles.pairingsShell} role="dialog" aria-label="Pairings">
        <header className={pairingStyles.pairingsHeader}>
          <div className={pairingStyles.pairingsIcon}>
            <LinkIcon />
          </div>
          <div className={pairingStyles.pairingsHeaderText}>
            <h2>Pairings</h2>
            <p>DJ-curated transitions weighted into pass-1 scoring.</p>
          </div>
          <div className={pairingStyles.pairingsStats}>
            <span><strong>{pairings.length}</strong> saved</span>
            <span><strong>{totalUses}</strong> uses</span>
          </div>
          <button type="button" className={sharedStyles.iconBtn} onClick={onClose} aria-label="Close">
            x
          </button>
        </header>
        <div className={pairingStyles.pairingsBody}>
          <aside className={pairingStyles.pairingsListCol}>
            <div className={pairingStyles.pairingsToolbar}>
              <input
                className={sharedStyles.imInput}
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search saved pairings..."
              />
              <button type="button" className="btn btn-sm" onClick={() => { setMode('add'); setSelectedId(null); }}>
                New
              </button>
            </div>
            <div className={pairingStyles.pairingsList}>
              {error && <div className={sharedStyles.imError}>{error}</div>}
              {filtered.map((pairing) => (
                <button
                  key={pairing.id}
                  type="button"
                  className={`${pairingStyles.pairingCard} ${selectedId === pairing.id ? pairingStyles.pairingCardActive : ''}`}
                  onClick={() => { setSelectedId(pairing.id); setMode('view'); }}
                >
                  <PairingMini pairing={pairing} />
                  <div className={pairingStyles.pairingCardTags}>
                    <CompatibilityChips from={pairing.from_track} into={pairing.into_track} />
                    <span className={pairingStyles.pairingUses}>x{pairing.use_count}</span>
                  </div>
                </button>
              ))}
              {!error && filtered.length === 0 && (
                <div className={pairingStyles.pairingsEmpty}>
                  {pairings.length === 0 ? 'No pairings yet.' : 'No pairings match that search.'}
                </div>
              )}
            </div>
          </aside>
          <main className={pairingStyles.pairingsDetailCol}>
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
              <div className={pairingStyles.pairingsEmpty}>Pick a pairing or create a new one.</div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
