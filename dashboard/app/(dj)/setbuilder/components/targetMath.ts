import type { SlotView } from './types';

export const DEFAULT_AVG_TRANSITION_OVERLAP_SEC = 8;

export interface TargetSettings {
  targetDurationSec: number | null;
  avgTransitionOverlapSec: number;
}

export interface TargetProjection {
  rawTotalSec: number;
  slotCount: number;
  transitionCount: number;
  transitionOverlapSec: number;
  effectiveSec: number;
  deltaSec: number | null;
  tier: TargetDeltaTier;
}

export type TargetDeltaTier = 'none' | 'on-target' | 'under' | 'over' | 'over-hard';

export interface TargetPreset {
  id: string;
  label: string;
  hint: string;
  seconds: number;
}

export const TARGET_PRESETS: TargetPreset[] = [
  { id: 'cocktail', label: '30m', hint: 'cocktail', seconds: 30 * 60 },
  { id: 'club-opener', label: '45m', hint: 'club opener', seconds: 45 * 60 },
  { id: 'wedding-dance', label: '1h', hint: 'wedding', seconds: 60 * 60 },
  { id: 'residency-short', label: '90m', hint: 'residency', seconds: 90 * 60 },
  { id: 'main-room', label: '2h', hint: 'main room', seconds: 120 * 60 },
  { id: 'late-night', label: '3h', hint: 'late night', seconds: 180 * 60 },
  { id: 'festival', label: '4h', hint: 'festival', seconds: 240 * 60 },
  { id: 'marathon', label: '6h', hint: 'all night', seconds: 360 * 60 },
];

export function effectiveDurationSec(totalSec: number, slotCount: number, overlapSec: number): number {
  const transitions = Math.max(0, slotCount - 1);
  return Math.max(0, Math.round(totalSec) - transitions * Math.max(0, Math.round(overlapSec)));
}

export function rawTargetSecForSlots(
  targetDurationSec: number | null,
  slotCount: number,
  overlapSec: number,
): number | null {
  if (targetDurationSec == null) return null;
  const transitions = Math.max(0, slotCount - 1);
  return Math.max(0, targetDurationSec + transitions * Math.max(0, Math.round(overlapSec)));
}

export function targetDeltaTier(deltaSec: number | null, targetDurationSec: number | null): TargetDeltaTier {
  if (deltaSec == null || targetDurationSec == null || targetDurationSec <= 0) return 'none';
  const tolerance = Math.max(60, targetDurationSec * 0.03);
  if (Math.abs(deltaSec) <= tolerance) return 'on-target';
  if (deltaSec < 0) return 'under';
  if (deltaSec > targetDurationSec * 0.15) return 'over-hard';
  return 'over';
}

export function projectTarget(slots: SlotView[], settings: TargetSettings): TargetProjection {
  const rawTotalSec = slots.reduce((acc, s) => acc + s.track.durationSec, 0);
  const slotCount = slots.length;
  const transitionCount = Math.max(0, slotCount - 1);
  const transitionOverlapSec = transitionCount * settings.avgTransitionOverlapSec;
  const effectiveSec = effectiveDurationSec(
    rawTotalSec,
    slotCount,
    settings.avgTransitionOverlapSec,
  );
  const deltaSec =
    settings.targetDurationSec == null ? null : effectiveSec - settings.targetDurationSec;
  return {
    rawTotalSec,
    slotCount,
    transitionCount,
    transitionOverlapSec,
    effectiveSec,
    deltaSec,
    tier: targetDeltaTier(deltaSec, settings.targetDurationSec),
  };
}

export function formatDuration(sec: number | null): string {
  if (sec == null) return 'No target';
  const rounded = Math.max(0, Math.round(sec / 60) * 60);
  const h = Math.floor(rounded / 3600);
  const m = Math.floor((rounded % 3600) / 60);
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0) return `${h}h`;
  return `${m}m`;
}

export function formatTimecode(sec: number | null): string {
  if (sec == null) return '--:--';
  const rounded = Math.max(0, Math.round(sec));
  const m = Math.floor(rounded / 60);
  const s = String(rounded % 60).padStart(2, '0');
  return `${m}:${s}`;
}

export function formatDelta(deltaSec: number | null): string {
  if (deltaSec == null) return 'Set target';
  const roundedDelta = Math.round(deltaSec / 60) * 60;
  const abs = formatTimecode(Math.abs(roundedDelta));
  if (roundedDelta === 0) return 'On target';
  return `${roundedDelta > 0 ? '+' : '-'}${abs}`;
}
