import type { SlotView } from './types';

/** Returns unlocked slots whose timeline start is strictly before the playhead. */
export function getUnlockedSlotIdsBeforePlayhead(slots: SlotView[], positionSec: number): number[] {
  let startSec = 0;
  const ids: number[] = [];
  for (const slot of slots) {
    if (startSec < positionSec && !slot.locked) ids.push(slot.id);
    startSec += slot.track.durationSec;
  }
  return ids;
}
