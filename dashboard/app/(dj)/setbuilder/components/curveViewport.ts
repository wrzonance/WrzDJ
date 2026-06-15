import type { SlotView } from './types';
import { effectiveTarget } from './types';

export type CurveLod = 'overview' | 'medium' | 'detail';

export const CURVE_LOD_THRESHOLDS = {
  overviewMaxMedianSlotPx: 6,
  detailMinMedianSlotPx: 28,
  minPxPerSecond: 0.02,
  maxPxPerSecond: 12,
  zoomStep: 1.35,
} as const;

export interface SlotTimeRange {
  idx: number;
  slot: SlotView;
  startSec: number;
  endSec: number;
  midSec: number;
}

export interface VisibleSlotBlock extends SlotTimeRange {
  x0: number;
  x1: number;
  xMid: number;
  width: number;
  energy: number;
  target: number;
}

export function clampPxPerSecond(pxPerSecond: number): number {
  if (!Number.isFinite(pxPerSecond)) return CURVE_LOD_THRESHOLDS.minPxPerSecond;
  return Math.min(
    CURVE_LOD_THRESHOLDS.maxPxPerSecond,
    Math.max(CURVE_LOD_THRESHOLDS.minPxPerSecond, pxPerSecond),
  );
}

export function fitPxPerSecond({
  totalSec,
  viewportWidth,
}: {
  totalSec: number;
  viewportWidth: number;
}): number {
  if (totalSec <= 0 || viewportWidth <= 1) return CURVE_LOD_THRESHOLDS.minPxPerSecond;
  return clampPxPerSecond(viewportWidth / totalSec);
}

export function curveViewportRange({
  scrollLeft,
  viewportWidth,
  pxPerSecond,
  totalSec,
}: {
  scrollLeft: number;
  viewportWidth: number;
  pxPerSecond: number;
  totalSec: number;
}): { startSec: number; endSec: number } {
  const scale = clampPxPerSecond(pxPerSecond);
  const startSec = Math.max(0, scrollLeft / scale);
  const spanSec = Math.max(1, viewportWidth / scale);
  return {
    startSec,
    endSec: Math.min(Math.max(totalSec, 1), startSec + spanSec),
  };
}

export function slotTimeRanges(slots: SlotView[]): SlotTimeRange[] {
  let cursor = 0;
  return slots.map((slot, idx) => {
    const durationSec = Math.max(0, slot.track.durationSec);
    const startSec = cursor;
    const endSec = cursor + durationSec;
    cursor = endSec;
    return {
      idx,
      slot,
      startSec,
      endSec,
      midSec: startSec + durationSec / 2,
    };
  });
}

export function visibleBlocksFromSlots({
  slots,
  visibleStartSec,
  visibleEndSec,
  pxPerSecond,
  overscanSec = 0,
}: {
  slots: SlotView[];
  visibleStartSec: number;
  visibleEndSec: number;
  pxPerSecond: number;
  overscanSec?: number;
}): VisibleSlotBlock[] {
  const start = Math.max(0, visibleStartSec - overscanSec);
  const end = visibleEndSec + overscanSec;
  const scale = clampPxPerSecond(pxPerSecond);
  return slotTimeRanges(slots)
    .filter((range) => range.endSec > start && range.startSec < end)
    .map((range) => {
      const x0 = (range.startSec - visibleStartSec) * scale;
      const x1 = (range.endSec - visibleStartSec) * scale;
      return {
        ...range,
        x0,
        x1,
        xMid: (range.midSec - visibleStartSec) * scale,
        width: Math.max(0, x1 - x0),
        energy: range.slot.track.energy,
        target: effectiveTarget(range.slot),
      };
    });
}

export function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

export function lodForMedianSlotWidth(widths: number[]): CurveLod {
  const med = median(widths);
  if (med < CURVE_LOD_THRESHOLDS.overviewMaxMedianSlotPx) return 'overview';
  if (med < CURVE_LOD_THRESHOLDS.detailMinMedianSlotPx) return 'medium';
  return 'detail';
}

export function zoomPxPerSecond({
  currentPxPerSecond,
  direction,
  scrollLeft,
  viewportWidth,
  totalSec,
}: {
  currentPxPerSecond: number;
  direction: 'in' | 'out';
  scrollLeft: number;
  viewportWidth: number;
  totalSec: number;
}): { pxPerSecond: number; scrollLeft: number } {
  const current = clampPxPerSecond(currentPxPerSecond);
  const multiplier =
    direction === 'in' ? CURVE_LOD_THRESHOLDS.zoomStep : 1 / CURVE_LOD_THRESHOLDS.zoomStep;
  const nextScale = clampPxPerSecond(current * multiplier);
  const centerPx = scrollLeft + viewportWidth / 2;
  const centerSec = centerPx / current;
  const nextScroll = centerSec * nextScale - viewportWidth / 2;
  const maxScroll = Math.max(0, totalSec * nextScale - viewportWidth);
  return {
    pxPerSecond: nextScale,
    scrollLeft: Math.min(maxScroll, Math.max(0, nextScroll)),
  };
}
