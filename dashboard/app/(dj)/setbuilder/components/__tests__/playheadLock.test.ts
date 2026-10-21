import { describe, expect, it } from 'vitest';
import type { SlotView } from '../types';
import { getUnlockedSlotIdsBeforePlayhead } from '../playheadLock';

function slot(id: number, durationSec: number, locked = false): SlotView {
  return {
    id,
    position: id - 1,
    locked,
    targetEnergy: null,
    transitionScore: null,
    nextPairingId: null,
    nextIsDjPairing: false,
    track: { id: `track-${id}`, title: `Track ${id}`, artist: 'Artist', durationSec, energy: 5, bpm: null, key: null },
  };
}

describe('getUnlockedSlotIdsBeforePlayhead', () => {
  // Regression for baseline 57cfcdc6867f: lock selection keeps exact start-time boundary semantics.
  it('uses cumulative duration, excludes the playhead boundary, and leaves locked slots out', () => {
    const slots = [
      slot(1, 10),
      slot(2, 20),
      slot(3, 30, true),
      slot(4, 40),
    ];

    expect(getUnlockedSlotIdsBeforePlayhead(slots, 30)).toEqual([1, 2]);
    expect(getUnlockedSlotIdsBeforePlayhead(slots, 61)).toEqual([1, 2, 4]);
  });
});
