import type { TransportCommandIn } from '@/lib/api-types';
import type { SlotView } from './types';

export const PREV_RESTART_THRESHOLD_SEC = 3;

export function totalDuration(slots: SlotView[]): number {
  return slots.reduce((acc, slot) => acc + slot.track.durationSec, 0);
}

export function slotStartSec(slots: SlotView[], idx: number): number {
  return slots.slice(0, Math.max(0, idx)).reduce((acc, slot) => acc + slot.track.durationSec, 0);
}

export function slotIndexAtPosition(slots: SlotView[], positionSec: number): number {
  if (slots.length === 0) return -1;
  const clamped = Math.max(0, Math.min(positionSec, Math.max(0, totalDuration(slots) - 0.001)));
  let cursor = 0;
  for (let i = 0; i < slots.length; i++) {
    cursor += slots[i].track.durationSec;
    if (clamped < cursor) return i;
  }
  return slots.length - 1;
}

export function localPositionSec(slots: SlotView[], idx: number, positionSec: number): number {
  const slot = slots[idx];
  if (!slot) return 0;
  return Math.max(0, Math.min(slot.track.durationSec, positionSec - slotStartSec(slots, idx)));
}

export function previousIndex(slots: SlotView[], idx: number, positionSec: number): number {
  if (idx <= 0) return 0;
  return localPositionSec(slots, idx, positionSec) >= PREV_RESTART_THRESHOLD_SEC ? idx : idx - 1;
}

export function commandPayload(
  slots: SlotView[],
  idx: number,
  action: TransportCommandIn['action'],
  positionSec: number,
): TransportCommandIn | null {
  const slot = slots[idx];
  if (!slot) return null;
  return {
    action,
    source: 'tidal',
    slot_index: idx,
    track_id: slot.track.id,
    title: slot.track.title,
    artist: slot.track.artist,
    position_sec: localPositionSec(slots, idx, positionSec),
    duration_sec: slot.track.durationSec,
  };
}
