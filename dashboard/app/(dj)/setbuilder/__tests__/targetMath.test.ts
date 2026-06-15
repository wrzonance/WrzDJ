import { describe, expect, it } from 'vitest';
import {
  effectiveDurationSec,
  formatDelta,
  projectTarget,
  rawTargetSecForSlots,
  targetDeltaTier,
} from '../components/targetMath';
import type { SlotView } from '../components/types';

function slot(durationSec: number): SlotView {
  return {
    id: durationSec,
    position: 0,
    locked: false,
    targetEnergy: null,
    transitionScore: null,
    nextPairingId: null,
    nextIsDjPairing: false,
    track: {
      id: `t-${durationSec}`,
      title: 'Track',
      artist: 'Artist',
      durationSec,
      energy: 5,
      bpm: null,
      key: null,
    },
  };
}

describe('targetMath', () => {
  it('subtracts transition overlap from effective duration', () => {
    expect(effectiveDurationSec(1800, 6, 8)).toBe(1760);
    expect(effectiveDurationSec(1800, 1, 8)).toBe(1800);
  });

  it('projects raw, overlap, effective and delta', () => {
    const projection = projectTarget([slot(300), slot(300), slot(300)], {
      targetDurationSec: 870,
      avgTransitionOverlapSec: 15,
    });

    expect(projection.rawTotalSec).toBe(900);
    expect(projection.transitionOverlapSec).toBe(30);
    expect(projection.effectiveSec).toBe(870);
    expect(projection.deltaSec).toBe(0);
    expect(projection.tier).toBe('on-target');
  });

  it('moves the raw target marker as overlap changes', () => {
    expect(rawTargetSecForSlots(600, 4, 0)).toBe(600);
    expect(rawTargetSecForSlots(600, 4, 10)).toBe(630);
  });

  it('tiers deltas by target-relative severity', () => {
    expect(targetDeltaTier(20, 3600)).toBe('on-target');
    expect(targetDeltaTier(-600, 3600)).toBe('under');
    expect(targetDeltaTier(300, 3600)).toBe('over');
    expect(targetDeltaTier(700, 3600)).toBe('over-hard');
  });

  it('formats signed delta labels', () => {
    expect(formatDelta(0)).toBe('On target');
    expect(formatDelta(600)).toBe('+10:00');
    expect(formatDelta(-3600)).toBe('-60:00');
  });
});
