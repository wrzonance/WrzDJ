'use client';

import { useEffect, useMemo, useState } from 'react';
import type { Pairing } from '@/lib/api/types';
import { BPM_TIER_COLORS, KEY_TIER_COLORS, bpmPercentDelta, camelotMixTier, fmtTime } from '../curve/curveMath';
import type { SlotView } from '../types';
import { TrackArt } from './PairingVisuals';

import pairingStyles from '../../setbuilder-pairings.module.css';
import sharedStyles from '../../setbuilder-shared.module.css';

export function PairingDetail({
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
  const [deletePending, setDeletePending] = useState(false);

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

  const deletePairing = async () => {
    if (deletePending) return;

    setDeletePending(true);
    try {
      await onDelete();
    } catch {
      // The parent displays mutation failures in the overlay's shared error region.
    } finally {
      setDeletePending(false);
    }
  };

  return (
    <div className={pairingStyles.pairingDetail}>
      <div className={pairingStyles.pairingHero}>
        <div className={pairingStyles.pairingHeroTrack}>
          <span className={pairingStyles.pairingRole}>FROM</span>
          <TrackArt track={pairing.from_track} />
          <strong>{pairing.from_track?.title ?? pairing.from_track_id}</strong>
          <span>{pairing.from_track?.artist ?? 'Unknown artist'}</span>
        </div>
        <div className={pairingStyles.pairingHeroArrow}>
          <span>-&gt;</span>
          {pairing.cue_in_sec != null && pairing.cue_in_sec > 0 && (
            <span className={pairingStyles.pairingCue}>cue @ {fmtTime(pairing.cue_in_sec)}</span>
          )}
        </div>
        <div className={pairingStyles.pairingHeroTrack}>
          <span className={pairingStyles.pairingRole}>INTO</span>
          <TrackArt track={pairing.into_track} />
          <strong>{pairing.into_track?.title ?? pairing.into_track_id}</strong>
          <span>{pairing.into_track?.artist ?? 'Unknown artist'}</span>
        </div>
      </div>

      <div className={pairingStyles.pairingStatsGrid}>
        <div className={pairingStyles.pairingStatCard} style={{ borderColor: BPM_TIER_COLORS[bpm.tier].stroke }}>
          <span>BPM delta</span>
          <strong style={{ color: BPM_TIER_COLORS[bpm.tier].chip }}>
            {bpm.pct == null ? '?' : `${bpm.pct.toFixed(1)}%`}
          </strong>
          <small>{pairing.from_track?.bpm ?? '-'} -&gt; {pairing.into_track?.bpm ?? '-'}</small>
        </div>
        <div className={pairingStyles.pairingStatCard} style={{ borderColor: KEY_TIER_COLORS[key.tier].stroke }}>
          <span>Camelot</span>
          <strong style={{ color: KEY_TIER_COLORS[key.tier].chip }}>{key.label}</strong>
          <small>{pairing.from_track?.camelot ?? '-'} -&gt; {pairing.into_track?.camelot ?? '-'}</small>
        </div>
        <div className={pairingStyles.pairingStatCard}>
          <span>Energy</span>
          <strong>
            {pairing.from_track?.energy ?? '-'} -&gt; {pairing.into_track?.energy ?? '-'}
          </strong>
          <small>slot vibe signal</small>
        </div>
        <div className={pairingStyles.pairingStatCard}>
          <span>Uses</span>
          <strong>{pairing.use_count}</strong>
          <small>captured transitions</small>
        </div>
      </div>

      <section className={pairingStyles.pairingSection}>
        <div className={pairingStyles.pairingSectionHead}>
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
              aria-label="Pairing note"
              className={pairingStyles.pairingTextarea}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={4}
              autoFocus
            />
            <div className={pairingStyles.pairingInlineActions}>
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
          <p className={pairingStyles.pairingNote}>
            {pairing.note || 'No note yet. Add cue, mixer, or crowd-read context.'}
          </p>
        )}
      </section>

      <div className={pairingStyles.pairingTags}>
        {(pairing.tags ?? []).map((tag) => (
          <span key={tag}>#{tag}</span>
        ))}
      </div>

      <div className={pairingStyles.pairingSetUse}>
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

      <div className={pairingStyles.pairingFooter}>
        <button
          type="button"
          className={`btn btn-sm ${sharedStyles.dangerBtn}`}
          disabled={deletePending}
          aria-busy={deletePending}
          onClick={() => void deletePairing()}
        >
          {deletePending ? 'Deleting pairing' : 'Delete pairing'}
        </button>
      </div>
    </div>
  );
}
