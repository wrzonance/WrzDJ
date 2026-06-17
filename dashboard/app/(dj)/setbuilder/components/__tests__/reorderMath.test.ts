import { describe, it, expect } from 'vitest';
import { buildMovedIds } from '../reorderMath';
import type { SlotView } from '../types';

function slot(id: number, locked = false): SlotView {
  return {
    id, position: id, locked, targetEnergy: null, transitionScore: 50,
    nextPairingId: null, nextIsDjPairing: false,
    track: { id: `t${id}`, title: `T${id}`, artist: `A${id}`, durationSec: 210, energy: 5, bpm: 120, key: '8A' },
  };
}

describe('buildMovedIds', () => {
  const slots = [slot(1), slot(2), slot(3)];

  it('moves a slot up one position', () => {
    expect(buildMovedIds(slots, 2, 'up')).toEqual([2, 1, 3]);
  });

  it('moves a slot down one position', () => {
    expect(buildMovedIds(slots, 2, 'down')).toEqual([1, 3, 2]);
  });

  it('returns null moving the first slot up (boundary)', () => {
    expect(buildMovedIds(slots, 1, 'up')).toBeNull();
  });

  it('returns null moving the last slot down (boundary)', () => {
    expect(buildMovedIds(slots, 3, 'down')).toBeNull();
  });

  it('returns null for an unknown slot id', () => {
    expect(buildMovedIds(slots, 999, 'up')).toBeNull();
  });

  it('returns null when the move would displace a locked slot', () => {
    const s = [slot(1), slot(2, true), slot(3)]; // lock at idx 1
    expect(buildMovedIds(s, 3, 'up')).toBeNull();
    expect(buildMovedIds(s, 1, 'down')).toBeNull();
  });

  it('allows a move that does not cross a locked slot', () => {
    const s = [slot(1), slot(2), slot(3, true), slot(4)]; // lock at idx 2
    expect(buildMovedIds(s, 1, 'down')).toEqual([2, 1, 3, 4]);
  });
});
