import { describe, expect, it } from 'vitest';
import type { SlotView } from '../components/types';
import {
  CURVE_LOD_THRESHOLDS,
  clampPxPerSecond,
  curveViewportRange,
  fitPxPerSecond,
  lodForMedianSlotWidth,
  slotTimeRanges,
  visibleBlocksFromSlots,
  zoomPxPerSecond,
} from '../components/curveViewport';

function mkSlot(idx: number, durationSec = 200): SlotView {
  return {
    id: idx + 1,
    position: idx,
    locked: false,
    targetEnergy: null,
    transitionScore: null,
    nextPairingId: null,
    nextIsDjPairing: false,
    track: {
      id: `t${idx}`,
      title: `Track ${idx}`,
      artist: `Artist ${idx}`,
      durationSec,
      energy: 5 + (idx % 4),
      bpm: 120,
      key: '8A',
    },
  };
}

describe('curveViewport helpers', () => {
  it('computes slot time ranges from ordered slot durations', () => {
    const ranges = slotTimeRanges([mkSlot(0, 100), mkSlot(1, 200), mkSlot(2, 300)]);
    expect(ranges.map((r) => [r.startSec, r.endSec, r.midSec])).toEqual([
      [0, 100, 50],
      [100, 300, 200],
      [300, 600, 450],
    ]);
  });

  it('fits full duration into the visible viewport with a bounded scale', () => {
    expect(fitPxPerSecond({ totalSec: 1000, viewportWidth: 500 })).toBe(0.5);
    expect(fitPxPerSecond({ totalSec: 0, viewportWidth: 500 })).toBe(
      CURVE_LOD_THRESHOLDS.minPxPerSecond,
    );
    expect(fitPxPerSecond({ totalSec: 1000, viewportWidth: 1 })).toBe(
      CURVE_LOD_THRESHOLDS.minPxPerSecond,
    );
  });

  it('derives visible seconds from scroll and scale', () => {
    expect(
      curveViewportRange({ scrollLeft: 250, viewportWidth: 500, pxPerSecond: 2, totalSec: 1000 }),
    ).toEqual({
      startSec: 125,
      endSec: 375,
    });
  });

  it('returns only visible blocks plus overscan in viewport-local coordinates', () => {
    const slots = Array.from({ length: 20 }, (_, i) => mkSlot(i, 60));
    const blocks = visibleBlocksFromSlots({
      slots,
      visibleStartSec: 300,
      visibleEndSec: 600,
      pxPerSecond: 2,
      overscanSec: 60,
    });
    expect(blocks[0].idx).toBe(4);
    expect(blocks.at(-1)?.idx).toBe(10);
    expect(blocks[0].x0).toBe(-120);
    expect(blocks[1].x0).toBe(0);
    expect(blocks[1].width).toBe(120);
  });

  it('uses median visible slot width for LOD thresholds', () => {
    expect(lodForMedianSlotWidth([2, 3, 4])).toBe('overview');
    expect(lodForMedianSlotWidth([6, 12, 20])).toBe('medium');
    expect(lodForMedianSlotWidth([28, 60, 90])).toBe('detail');
  });

  it('zooms around a center point without exceeding configured bounds', () => {
    const next = zoomPxPerSecond({
      currentPxPerSecond: 1,
      direction: 'in',
      scrollLeft: 200,
      viewportWidth: 400,
      totalSec: 1000,
    });
    expect(next.pxPerSecond).toBeCloseTo(1.35);
    expect(next.scrollLeft).toBeCloseTo(340);

    const clamped = clampPxPerSecond(999);
    expect(clamped).toBe(CURVE_LOD_THRESHOLDS.maxPxPerSecond);
  });
});
