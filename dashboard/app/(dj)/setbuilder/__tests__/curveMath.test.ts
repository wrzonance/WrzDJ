import { describe, it, expect } from 'vitest';
import {
  interpolateEnergy,
  slotMidpoints,
  bpmPercentDelta,
  camelotMixTier,
  bpmCompat,
  camelotCompat,
  parseCamelot,
  rankReplacementCandidates,
  slotBlocksFromSlots,
  fmtTime,
  VIBE_PRESETS,
  REPLACE_PROMPT_THRESHOLD,
} from '../components/curveMath';
import type { SlotView, TrackView } from '../components/types';
import { slotViewFromApi, effectiveTarget } from '../components/types';

function mkTrack(over: Partial<TrackView> = {}): TrackView {
  return {
    id: 't1',
    title: 'Song',
    artist: 'Artist',
    durationSec: 200,
    energy: 5,
    bpm: 120,
    key: '8A',
    ...over,
  };
}

function mkSlot(idx: number, over: Partial<TrackView> = {}, target: number | null = null): SlotView {
  return {
    id: idx + 1,
    position: idx,
    locked: false,
    targetEnergy: target,
    track: mkTrack({ id: `t${idx}`, ...over }),
  };
}

describe('interpolateEnergy', () => {
  const linear = [
    { t: 0, e: 0, label: null, slow_start: false, slow_end: false },
    { t: 1, e: 10, label: null, slow_start: false, slow_end: false },
  ];

  it('interpolates linearly', () => {
    expect(interpolateEnergy(linear, 0.5)).toBeCloseTo(5);
    expect(interpolateEnergy(linear, 0.25)).toBeCloseTo(2.5);
  });

  it('clamps t outside [0,1]', () => {
    expect(interpolateEnergy(linear, -1)).toBe(0);
    expect(interpolateEnergy(linear, 2)).toBe(10);
  });

  it('handles multi-segment curves', () => {
    const pts = [
      { t: 0, e: 2, label: null, slow_start: false, slow_end: false },
      { t: 0.5, e: 8, label: null, slow_start: false, slow_end: false },
      { t: 1, e: 4, label: null, slow_start: false, slow_end: false },
    ];
    expect(interpolateEnergy(pts, 0.25)).toBeCloseTo(5);
    expect(interpolateEnergy(pts, 0.75)).toBeCloseTo(6);
  });
});

describe('slotMidpoints', () => {
  it('uses duration-weighted midpoints', () => {
    const slots = [mkSlot(0, { durationSec: 100 }), mkSlot(1, { durationSec: 300 })];
    expect(slotMidpoints(slots)).toEqual([0.125, 0.625]);
  });
});

describe('bpmPercentDelta (percentage thresholds — acceptance)', () => {
  it('≤2% is match', () => {
    // 100 → 102 = 1.96% of destination 102
    expect(bpmPercentDelta(100, 102).tier).toBe('match');
  });
  it('2-5% is good', () => {
    expect(bpmPercentDelta(100, 104).tier).toBe('good'); // 3.85%
  });
  it('5-8% is stretch', () => {
    expect(bpmPercentDelta(100, 107).tier).toBe('stretch'); // 6.54%
  });
  it('>8% is clash', () => {
    expect(bpmPercentDelta(100, 120).tier).toBe('clash'); // 16.7%
  });
  it('detects half/double time: 80 vs 160 is a match, not a clash', () => {
    const d = bpmPercentDelta(80, 160);
    expect(d.tier).toBe('match');
    expect(d.halfDouble).toBe(true);
    expect(d.pct).toBeCloseTo(0);
  });
  it('same large absolute delta can be different tiers at different tempos (percentage, not absolute)', () => {
    // +8 BPM at 178 destination = 4.5% (good); +8 at 88 destination = 9.1% (clash)
    expect(bpmPercentDelta(170, 178).tier).toBe('good');
    expect(bpmPercentDelta(80, 88).tier).toBe('clash');
  });
  it('unknown when missing', () => {
    expect(bpmPercentDelta(null, 120).tier).toBe('unknown');
  });
});

describe('parseCamelot / camelotMixTier', () => {
  it('parses camelot codes', () => {
    expect(parseCamelot('8A')).toEqual({ num: 8, letter: 'A' });
    expect(parseCamelot('12b')).toEqual({ num: 12, letter: 'B' });
    expect(parseCamelot('13A')).toEqual({ num: null, letter: null });
    expect(parseCamelot(null)).toEqual({ num: null, letter: null });
  });
  it('same key and relative maj/min are perfect', () => {
    expect(camelotMixTier('8A', '8A').tier).toBe('perfect');
    expect(camelotMixTier('8A', '8B').tier).toBe('perfect');
  });
  it('adjacent same-ring is perfect, cross-ring ±1 is good', () => {
    expect(camelotMixTier('8A', '9A').tier).toBe('perfect');
    expect(camelotMixTier('8A', '9B').tier).toBe('good');
  });
  it('wraps the wheel: 12A ↔ 1A is adjacent', () => {
    expect(camelotMixTier('12A', '1A').tier).toBe('perfect');
  });
  it('far keys clash', () => {
    expect(camelotMixTier('8A', '2A').tier).toBe('clash');
  });
  it('unknown keys are unknown', () => {
    expect(camelotMixTier(null, '8A').tier).toBe('unknown');
  });
});

describe('compat scores', () => {
  it('bpmCompat honors half-time', () => {
    expect(bpmCompat(80, 160)).toBe(1.0);
    expect(bpmCompat(120, 121)).toBe(1.0);
    expect(bpmCompat(100, 150)).toBe(0.15);
  });
  it('camelotCompat tiers', () => {
    expect(camelotCompat('8A', '8A')).toBe(1.0);
    expect(camelotCompat('8A', '8B')).toBe(0.9);
    expect(camelotCompat('8A', '9A')).toBe(0.85);
    expect(camelotCompat(null, '8A')).toBe(0.5);
  });
});

describe('rankReplacementCandidates', () => {
  const pool: TrackView[] = [
    mkTrack({ id: 'a', energy: 8, bpm: 122, key: '8A' }),
    mkTrack({ id: 'b', energy: 7.5, bpm: 150, key: '2B' }),
    mkTrack({ id: 'c', energy: 3, bpm: 120, key: '8A' }), // too far from target 8
    mkTrack({ id: 'd', energy: 8, bpm: 121, key: '9A' }),
    mkTrack({ id: 'e', energy: 8.2, bpm: 123, key: '8B' }),
    mkTrack({ id: 'f', energy: 7.8, bpm: 119, key: '8A' }),
    mkTrack({ id: 'g', energy: 8.1, bpm: 124, key: '7A' }),
    mkTrack({ id: 'in-set', energy: 8, bpm: 122, key: '8A' }),
  ];
  const prev = mkTrack({ id: 'prev', bpm: 120, key: '8A' });

  it('excludes in-set tracks, filters ±2.5 energy, caps at top 5', () => {
    const ranked = rankReplacementCandidates(8, prev, pool, new Set(['in-set']));
    expect(ranked.length).toBe(5);
    expect(ranked.map((c) => c.track.id)).not.toContain('in-set');
    expect(ranked.map((c) => c.track.id)).not.toContain('c');
  });

  it('ranks energy+bpm+key fit highest first', () => {
    const ranked = rankReplacementCandidates(8, prev, pool, new Set());
    expect(ranked[0].score).toBeGreaterThanOrEqual(ranked[ranked.length - 1].score);
    // 'a' (exact energy, close bpm, same key) makes the cut; 'b' (bpm jump +
    // key clash) scores worst of the 7 eligible and is cut from the top 5.
    const ids = ranked.map((c) => c.track.id);
    expect(ids).toContain('a');
    expect(ids).not.toContain('b');
  });

  it('threshold constant matches the spec', () => {
    expect(REPLACE_PROMPT_THRESHOLD).toBe(0.8);
  });
});

describe('slotBlocksFromSlots / effectiveTarget', () => {
  it('sizes blocks by duration and applies target fallback to track energy', () => {
    const slots = [
      mkSlot(0, { durationSec: 100, energy: 4 }),
      mkSlot(1, { durationSec: 300, energy: 6 }, 9),
    ];
    const blocks = slotBlocksFromSlots(slots, 400);
    expect(blocks[0].width).toBeCloseTo(100);
    expect(blocks[1].width).toBeCloseTo(300);
    expect(blocks[0].target).toBe(4); // null target → track energy
    expect(blocks[1].target).toBe(9);
    expect(effectiveTarget(slots[0])).toBe(4);
  });
});

describe('slotViewFromApi', () => {
  it('fills safe defaults for missing track metadata', () => {
    const v = slotViewFromApi({
      id: 7,
      position: 2,
      track_id: null,
      locked: false,
      target_energy: null,
      notes: null,
      transition_score: null,
      transition_warnings: null,
      pool_track_id: null,
      title: null,
      artist: null,
      bpm: null,
      key: null,
      camelot: null,
      energy: null,
      duration_sec: null,
    });
    expect(v.track.durationSec).toBe(210);
    expect(v.track.energy).toBe(5);
    expect(v.targetEnergy).toBeNull();
  });
});

describe('misc', () => {
  it('fmtTime', () => {
    expect(fmtTime(75)).toBe('1:15');
    expect(fmtTime(3660)).toBe('1:01h');
  });
  it('15 vibe presets with the spec anchors', () => {
    expect(VIBE_PRESETS.length).toBe(15);
    const labels = VIBE_PRESETS.map((p) => p.label);
    expect(labels).toContain('First Dance');
    expect(labels).toContain('Cocktail Hour');
    expect(labels).toContain('Peak Build');
  });
});
