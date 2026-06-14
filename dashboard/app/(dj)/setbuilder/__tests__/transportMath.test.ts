import { describe, expect, it } from 'vitest';
import {
  commandPayload,
  localPositionSec,
  previousIndex,
  slotIndexAtPosition,
  slotStartSec,
  totalDuration,
} from '../components/transportMath';
import type { SlotView } from '../components/types';

function slot(idx: number, durationSec: number): SlotView {
  return {
    id: idx + 1,
    position: idx,
    locked: false,
    targetEnergy: null,
    transitionScore: null,
    nextPairingId: null,
    nextIsDjPairing: false,
    track: {
      id: `tidal:${idx + 1}`,
      title: `Track ${idx + 1}`,
      artist: `Artist ${idx + 1}`,
      durationSec,
      energy: 5,
      bpm: 120 + idx,
      key: '8A',
    },
  };
}

const slots = [slot(0, 100), slot(1, 200), slot(2, 150)];

describe('transportMath', () => {
  it('maps absolute set positions to slots and local track time', () => {
    expect(totalDuration(slots)).toBe(450);
    expect(slotStartSec(slots, 2)).toBe(300);
    expect(slotIndexAtPosition(slots, 0)).toBe(0);
    expect(slotIndexAtPosition(slots, 100)).toBe(1);
    expect(slotIndexAtPosition(slots, 449.5)).toBe(2);
    expect(localPositionSec(slots, 1, 125)).toBe(25);
  });

  it('uses the 3-second previous convention', () => {
    expect(previousIndex(slots, 1, 101)).toBe(0);
    expect(previousIndex(slots, 1, 103)).toBe(1);
    expect(previousIndex(slots, 0, 12)).toBe(0);
  });

  it('builds a Tidal-only Bridge transport payload', () => {
    expect(commandPayload(slots, 1, 'play', 125)).toEqual({
      action: 'play',
      source: 'tidal',
      slot_index: 1,
      track_id: 'tidal:2',
      title: 'Track 2',
      artist: 'Artist 2',
      position_sec: 25,
      duration_sec: 200,
    });
  });
});
