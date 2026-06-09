/**
 * View-model types for the energy-curve editor (#389).
 *
 * Track metadata flows from the pool (#388) / two-pass algorithm (#390);
 * until those land, `slotViewFromApi` fills safe defaults so the curve is
 * renderable from the bare Phase 0 slot rows.
 */

import type { SetSlotOut } from '@/lib/api-types';

export interface TrackView {
  id: string;
  title: string;
  artist: string;
  durationSec: number;
  /** Intrinsic track energy 0-10 (vibe-sourced). */
  energy: number;
  bpm: number | null;
  /** Camelot key string, e.g. "8A". */
  key: string | null;
}

export interface SlotView {
  id: number;
  position: number;
  locked: boolean;
  /** Explicit target; null = fall back to track energy. */
  targetEnergy: number | null;
  track: TrackView;
}

/** A vibe window in normalized timeline coordinates (t in [0,1]). */
export interface VibeWindowView {
  id: string;
  t0: number;
  t1: number;
  label: string;
}

export const DEFAULT_TRACK_DURATION_SEC = 210;
export const DEFAULT_TRACK_ENERGY = 5;

export function slotViewFromApi(slot: SetSlotOut): SlotView {
  return {
    id: slot.id,
    position: slot.position,
    locked: slot.locked,
    targetEnergy: slot.target_energy ?? null,
    track: {
      id: slot.track_id ?? `slot-${slot.id}`,
      title: slot.track_id ?? `Slot ${slot.position + 1}`,
      artist: '',
      durationSec: DEFAULT_TRACK_DURATION_SEC,
      energy: DEFAULT_TRACK_ENERGY,
      bpm: null,
      key: null,
    },
  };
}

/** Effective target for a slot: explicit target, else the track's energy. */
export function effectiveTarget(slot: SlotView): number {
  return slot.targetEnergy ?? slot.track.energy;
}
