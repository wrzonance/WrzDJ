/**
 * Pure math + presets for the energy-curve editor (#389).
 *
 * Mirrors the design-bundle helpers exactly:
 * - BPM friction is PERCENTAGE-based (relative to the destination tempo)
 *   with half/double-time detection — tiers at ≤2% / ≤5% / ≤8% / >8%.
 * - Camelot friction tiers come from wheel distance + ring crossing.
 * - Replacement ranking: 0.55 energy match + 0.25 BPM continuity +
 *   0.20 Camelot adjacency, candidates within ±2.5 energy, top 5.
 */

import type { CurvePoint } from '@/lib/api-types';
import type { SlotView, TrackView } from './types';
import { effectiveTarget } from './types';

// ---------------------------------------------------------------------------
// Interpolation (piecewise linear — matches server curve.py)
// ---------------------------------------------------------------------------

export function interpolateEnergy(points: CurvePoint[], t: number): number {
  if (points.length === 0) return 5;
  const tt = Math.max(0, Math.min(1, t));
  if (tt <= points[0].t) return points[0].e;
  if (tt >= points[points.length - 1].t) return points[points.length - 1].e;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (tt >= a.t && tt <= b.t) {
      const span = b.t - a.t;
      if (span <= 0) return b.e;
      return a.e + ((b.e - a.e) * (tt - a.t)) / span;
    }
  }
  return points[points.length - 1].e;
}

/** Normalized slot midpoints from track durations (uniform when total is 0). */
export function slotMidpoints(slots: SlotView[]): number[] {
  const total = slots.reduce((acc, s) => acc + s.track.durationSec, 0);
  if (total <= 0) return slots.map((_, i) => (i + 0.5) / slots.length);
  let cur = 0;
  return slots.map((s) => {
    const mid = (cur + s.track.durationSec / 2) / total;
    cur += s.track.durationSec;
    return mid;
  });
}

// ---------------------------------------------------------------------------
// BPM friction (percentage thresholds + half/double-time)
// ---------------------------------------------------------------------------

export type BpmTier = 'match' | 'good' | 'stretch' | 'clash' | 'unknown';

export interface BpmDelta {
  tier: BpmTier;
  /** Percent of destination tempo (0-100); null when either BPM missing. */
  pct: number | null;
  halfDouble: boolean;
}

export function bpmPercentDelta(b1: number | null, b2: number | null): BpmDelta {
  if (!b1 || !b2) return { tier: 'unknown', pct: null, halfDouble: false };
  const candidates = [
    { delta: Math.abs(b1 - b2), halfDouble: false },
    { delta: Math.abs(b1 - b2 * 0.5), halfDouble: true },
    { delta: Math.abs(b1 - b2 * 2.0), halfDouble: true },
  ];
  let best = candidates[0];
  for (const c of candidates) if (c.delta < best.delta) best = c;
  const pct = (best.delta / b2) * 100;
  let tier: BpmTier;
  if (pct <= 2) tier = 'match'; // ≤2% — inaudible drift
  else if (pct <= 5) tier = 'good'; // 2-5% — well within pitch fader
  else if (pct <= 8) tier = 'stretch'; // 5-8% — at the pitch-fader edge
  else tier = 'clash'; // >8% — intentional shift required
  return { tier, pct, halfDouble: best.halfDouble };
}

// ---------------------------------------------------------------------------
// Camelot parsing + friction tiers
// ---------------------------------------------------------------------------

interface CamelotInfo {
  num: number | null;
  letter: 'A' | 'B' | null;
}

export function parseCamelot(key: string | null): CamelotInfo {
  if (!key) return { num: null, letter: null };
  const m = key.trim().toUpperCase().match(/^([1-9]|1[0-2])([AB])$/);
  if (!m) return { num: null, letter: null };
  return { num: parseInt(m[1], 10), letter: m[2] as 'A' | 'B' };
}

export type KeyTier = 'perfect' | 'good' | 'ok' | 'clash' | 'unknown';

export interface KeyMix {
  tier: KeyTier;
  dist: number | null;
  label: string;
}

export function camelotMixTier(k1: string | null, k2: string | null): KeyMix {
  const a = parseCamelot(k1);
  const b = parseCamelot(k2);
  if (!a.num || !b.num) return { tier: 'unknown', dist: null, label: '?' };
  if (a.num === b.num && a.letter === b.letter) {
    return { tier: 'perfect', dist: 0, label: 'Same key' };
  }
  if (a.num === b.num) return { tier: 'perfect', dist: 0, label: 'Relative maj/min' };
  const dist = Math.min(Math.abs(a.num - b.num), 12 - Math.abs(a.num - b.num));
  if (a.letter === b.letter && dist === 1) return { tier: 'perfect', dist, label: 'Adjacent · ±1' };
  if (a.letter !== b.letter && dist === 1) {
    return { tier: 'good', dist, label: 'Energy shift · ±1 cross' };
  }
  if (a.letter === b.letter && dist === 2) return { tier: 'good', dist, label: 'Adjacent · ±2' };
  if (dist === 2) return { tier: 'ok', dist, label: 'Mood shift · ±2 cross' };
  if (dist === 3) return { tier: 'ok', dist, label: '±3 on wheel' };
  return { tier: 'clash', dist, label: `±${dist} clash` };
}

// ---------------------------------------------------------------------------
// Compatibility scores (0-1) for replacement ranking
// ---------------------------------------------------------------------------

export function bpmCompat(b1: number | null, b2: number | null): number {
  if (!b1 || !b2) return 0.5;
  const diff = Math.min(Math.abs(b1 - b2), Math.abs(b1 - b2 * 0.5), Math.abs(b1 - b2 * 2.0));
  if (diff <= 3) return 1.0;
  if (diff <= 6) return 0.85;
  if (diff <= 12) return 0.6;
  if (diff <= 20) return 0.35;
  return 0.15;
}

export function camelotCompat(k1: string | null, k2: string | null): number {
  const a = parseCamelot(k1);
  const b = parseCamelot(k2);
  if (!a.num || !b.num) return 0.5;
  if (a.num === b.num && a.letter === b.letter) return 1.0;
  if (a.num === b.num) return 0.9;
  const diff = Math.min(Math.abs(a.num - b.num), 12 - Math.abs(a.num - b.num));
  if (a.letter === b.letter && diff === 1) return 0.85;
  if (a.letter === b.letter && diff === 2) return 0.55;
  if (a.letter !== b.letter && diff === 1) return 0.4;
  return 0.2;
}

export interface ReplacementCandidate {
  track: TrackView;
  energyDist: number;
  score: number;
}

/** Threshold at which a drag-release prompts the replacement popover. */
export const REPLACE_PROMPT_THRESHOLD = 0.8;

export function rankReplacementCandidates(
  targetEnergy: number,
  prevTrack: TrackView | null,
  pool: TrackView[],
  inSetIds: ReadonlySet<string>,
): ReplacementCandidate[] {
  return pool
    .filter((t) => !inSetIds.has(t.id))
    .map((t) => {
      const energyDist = Math.abs(t.energy - targetEnergy);
      const bpmFit = prevTrack ? bpmCompat(prevTrack.bpm, t.bpm) : 0.8;
      const keyFit = prevTrack ? camelotCompat(prevTrack.key, t.key) : 0.8;
      const score = (1 - Math.min(energyDist / 4, 1)) * 0.55 + bpmFit * 0.25 + keyFit * 0.2;
      return { track: t, energyDist, score };
    })
    .filter((c) => c.energyDist <= 2.5)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);
}

// ---------------------------------------------------------------------------
// Tier color palettes (design bundle)
// ---------------------------------------------------------------------------

export interface TierColor {
  stroke: string;
  fill: string;
  chip: string;
  chipBg: string;
}

export const BPM_TIER_COLORS: Record<BpmTier, TierColor> = {
  match: { stroke: '#22c55e', fill: 'rgba(34,197,94,0.18)', chip: '#4ade80', chipBg: 'rgba(34,197,94,0.14)' },
  good: { stroke: '#84cc16', fill: 'rgba(132,204,22,0.18)', chip: '#a3e635', chipBg: 'rgba(132,204,22,0.14)' },
  stretch: { stroke: '#f59e0b', fill: 'rgba(245,158,11,0.18)', chip: '#fbbf24', chipBg: 'rgba(245,158,11,0.14)' },
  clash: { stroke: '#ef4444', fill: 'rgba(239,68,68,0.20)', chip: '#f87171', chipBg: 'rgba(239,68,68,0.14)' },
  unknown: { stroke: '#6b7280', fill: 'rgba(107,114,128,0.15)', chip: '#9ca3af', chipBg: 'rgba(107,114,128,0.14)' },
};

export const KEY_TIER_COLORS: Record<KeyTier, TierColor> = {
  perfect: BPM_TIER_COLORS.match,
  good: BPM_TIER_COLORS.good,
  ok: BPM_TIER_COLORS.stretch,
  clash: BPM_TIER_COLORS.clash,
  unknown: BPM_TIER_COLORS.unknown,
};

// ---------------------------------------------------------------------------
// Slot block geometry
// ---------------------------------------------------------------------------

export interface SlotBlock {
  idx: number;
  slot: SlotView;
  x0: number;
  x1: number;
  xMid: number;
  width: number;
  /** Intrinsic track energy. */
  energy: number;
  /** Effective target (drag override applied by caller). */
  target: number;
}

export function slotBlocksFromSlots(slots: SlotView[], width: number): SlotBlock[] {
  const total = slots.reduce((acc, s) => acc + s.track.durationSec, 0);
  if (total <= 0) return [];
  const blocks: SlotBlock[] = [];
  let cur = 0;
  for (let i = 0; i < slots.length; i++) {
    const s = slots[i];
    const t0 = cur / total;
    const t1 = (cur + s.track.durationSec) / total;
    blocks.push({
      idx: i,
      slot: s,
      x0: t0 * width,
      x1: t1 * width,
      xMid: ((t0 + t1) / 2) * width,
      width: Math.max(1, (t1 - t0) * width),
      energy: s.track.energy,
      target: effectiveTarget(s),
    });
    cur += s.track.durationSec;
  }
  return blocks;
}

export function fmtTime(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}h`;
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

// ---------------------------------------------------------------------------
// Vibe-window presets (15 — design bundle)
// ---------------------------------------------------------------------------

export interface VibePreset {
  id: string;
  label: string;
  energyBias: [number, number];
  hint: string;
}

export const VIBE_PRESETS: VibePreset[] = [
  { id: 'slow-dance', label: 'Slow Dance', energyBias: [3, 5], hint: 'tender · partner sway · 70-90 BPM' },
  { id: 'first-dance', label: 'First Dance', energyBias: [3, 4], hint: 'intimate · the couple’s song' },
  { id: 'parent-dance', label: 'Parent Dance', energyBias: [3, 5], hint: 'sentimental · multigenerational' },
  { id: 'cocktail', label: 'Cocktail Hour', energyBias: [3, 5], hint: 'conversational · jazz/soul/standards' },
  { id: 'dinner', label: 'Dinner', energyBias: [2, 4], hint: 'background · low BPM · vocals OK' },
  { id: 'cake-cutting', label: 'Cake Cutting', energyBias: [5, 7], hint: 'feel-good · short build' },
  { id: 'bouquet-toss', label: 'Bouquet Toss', energyBias: [7, 9], hint: 'singles anthem · empowered · sing-along' },
  { id: 'garter-toss', label: 'Garter Toss', energyBias: [7, 9], hint: 'cheeky · uptempo' },
  { id: 'money-dance', label: 'Money Dance', energyBias: [5, 7], hint: 'cultural · uptempo · 3-5 min' },
  { id: 'peak-build', label: 'Peak Build', energyBias: [7, 10], hint: 'energy lift into the drop' },
  { id: 'hype-up', label: 'Hype Up', energyBias: [9, 10], hint: 'maximum · anthem stack' },
  { id: 'sing-along', label: 'Sing-along', energyBias: [6, 8], hint: 'every-line-known · crowd vocals' },
  { id: 'breather', label: 'Breather', energyBias: [4, 6], hint: 'cool-down between peaks' },
  { id: 'last-call', label: 'Last Call', energyBias: [5, 7], hint: 'final ramp · 1-2 anthems' },
  { id: 'send-off', label: 'Send-off', energyBias: [5, 7], hint: 'closer · grand finale tone' },
];

export const BUILTIN_TEMPLATE_NAMES = ['Open-Format', 'Wedding', 'Prom', 'Club Peak'] as const;
