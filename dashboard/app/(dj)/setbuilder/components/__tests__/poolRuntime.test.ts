import { describe, expect, it } from 'vitest';
import {
  AVG_TRACK_LENGTH_SEC,
  poolRuntimeSec,
  projectedSlotCount,
} from '../poolRuntime';
import { DEFAULT_AVG_TRANSITION_OVERLAP_SEC } from '../targetMath';

const track = (duration_sec: number | null) => ({ duration_sec });

describe('poolRuntimeSec', () => {
  it('sums positive durations', () => {
    expect(poolRuntimeSec([track(240), track(240), track(240)])).toBe(720);
  });

  it('applies the avg fallback for missing/non-positive durations', () => {
    expect(poolRuntimeSec([track(240), track(null), track(0)])).toBe(
      240 + 2 * AVG_TRACK_LENGTH_SEC,
    );
  });

  it('is zero for an empty pool', () => {
    expect(poolRuntimeSec([])).toBe(0);
  });
});

describe('projectedSlotCount', () => {
  const overlap = DEFAULT_AVG_TRANSITION_OVERLAP_SEC; // 8

  it('matches the engine: 14-min target over 210s tracks is 5 overlap-aware slots', () => {
    // Mirrors test_build_set_fills_target_duration_deterministically (#538):
    // eff(840,4,8)=816 < 840 <= eff(1050,5,8)=1018, so 5 slots.
    const tracks = Array.from({ length: 20 }, () => track(210));
    expect(
      projectedSlotCount(tracks, { targetDurationSec: 14 * 60, avgTransitionOverlapSec: overlap }),
    ).toBe(5);
  });

  it('never exceeds the pool size', () => {
    const tracks = Array.from({ length: 3 }, () => track(210));
    expect(
      projectedSlotCount(tracks, { targetDurationSec: 60 * 60, avgTransitionOverlapSec: overlap }),
    ).toBe(3);
  });

  it('falls back to the 3h cap when no target is set (never the whole pool)', () => {
    // 400 x 210s tracks, no target: bounded by 3h fallback, never 400.
    const tracks = Array.from({ length: 400 }, () => track(210));
    const count = projectedSlotCount(tracks, {
      targetDurationSec: null,
      avgTransitionOverlapSec: overlap,
    });
    expect(count).toBeLessThan(400);
    expect(count).toBeLessThanOrEqual(60);
  });

  it('is overlap-aware: more overlap can need one more slot', () => {
    const tracks = Array.from({ length: 20 }, () => track(210));
    const noOverlap = projectedSlotCount(tracks, {
      targetDurationSec: 14 * 60,
      avgTransitionOverlapSec: 0,
    });
    const withOverlap = projectedSlotCount(tracks, {
      targetDurationSec: 14 * 60,
      avgTransitionOverlapSec: 60,
    });
    expect(withOverlap).toBeGreaterThan(noOverlap);
  });
});
