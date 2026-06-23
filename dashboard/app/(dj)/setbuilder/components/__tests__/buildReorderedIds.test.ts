import { describe, it, expect } from 'vitest';
import { buildReorderedIds } from '../reorderMath';
import type { SlotView } from '../types';

function slot(id: number, locked = false): SlotView {
  return {
    id, position: id, locked, targetEnergy: null, transitionScore: 50,
    nextPairingId: null, nextIsDjPairing: false,
    track: { id: `t${id}`, title: `T${id}`, artist: `A${id}`, durationSec: 210, energy: 5, bpm: 120, key: '8A' },
  };
}

describe('buildReorderedIds', () => {
  const slots = [slot(1), slot(2), slot(3)];

  it('moves a slot forward (drag idx 0 to end)', () => {
    // insertIdx === slots.length means "drop at the end"
    expect(buildReorderedIds(slots, 1, 3)).toEqual([2, 3, 1]);
  });

  it('moves a slot backward (drag idx 2 to front)', () => {
    expect(buildReorderedIds(slots, 3, 0)).toEqual([3, 1, 2]);
  });

  it('returns null for a no-op move', () => {
    // dragging idx 1 to insertIdx 1 (or 2, which resolves to the same slot) is a no-op
    expect(buildReorderedIds(slots, 2, 1)).toBeNull();
  });

  it('returns null for an unknown slot id', () => {
    expect(buildReorderedIds(slots, 999, 0)).toBeNull();
  });

  it('returns the new order when the move does not cross a locked slot', () => {
    const s = [slot(1), slot(2), slot(3, true)]; // lock at idx 2
    expect(buildReorderedIds(s, 1, 2)).toEqual([2, 1, 3]); // locked id 3 stays at idx 2
  });

  it('returns null when the move would displace a locked slot', () => {
    const s = [slot(1), slot(2, true), slot(3)]; // lock at idx 1
    expect(buildReorderedIds(s, 1, 3)).toBeNull(); // dragging idx0 to end crosses the lock
  });
});
