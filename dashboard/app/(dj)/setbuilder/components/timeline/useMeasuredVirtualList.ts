'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

export interface VirtualListItem {
  idx: number;
  key: number;
  top: number;
  height: number;
}

export interface UseMeasuredVirtualListInput {
  itemCount: number;
  estimateHeight: number;
  viewportHeight: number;
  scrollTop: number;
  overscan?: number;
  /** Changing this clears cached measured heights after structural list changes. */
  measurementKey?: string | number;
}

export interface UseMeasuredVirtualListResult {
  startIdx: number;
  /** Exclusive upper bound for visible item indices. */
  endIdx: number;
  beforeHeight: number;
  afterHeight: number;
  totalHeight: number;
  items: VirtualListItem[];
  setMeasuredHeight: (idx: number, height: number) => void;
  /** Returns totalHeight when called with itemCount. */
  scrollTopForIndex: (idx: number) => number;
  indexFromScrollTop: (top: number) => number;
}

interface MeasurementState {
  key: string | number | undefined;
  heights: Map<number, number>;
}

const EMPTY_MEASURED_HEIGHTS = new Map<number, number>();

function buildOffsets(itemCount: number, estimateHeight: number, measured: Map<number, number>) {
  const offsets: number[] = new Array(itemCount + 1);
  offsets[0] = 0;

  for (let i = 0; i < itemCount; i++) {
    offsets[i + 1] = offsets[i] + (measured.get(i) ?? estimateHeight);
  }

  return offsets;
}

function findIndexAtOffset(offsets: number[], top: number): number {
  if (offsets.length <= 1) return 0;

  const target = Number.isFinite(top) ? Math.max(0, top) : 0;
  let lo = 0;
  let hi = offsets.length - 2;

  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);

    if (offsets[mid + 1] <= target) lo = mid + 1;
    else if (offsets[mid] > target) hi = mid - 1;
    else return mid;
  }

  return Math.max(0, Math.min(offsets.length - 2, lo));
}

function findIndexBeforeOffset(offsets: number[], top: number): number {
  if (offsets.length <= 1) return 0;

  const target = Number.isFinite(top) ? Math.max(0, top) : 0;
  let lo = 0;
  let hi = offsets.length - 1;

  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);

    if (offsets[mid] < target) lo = mid + 1;
    else hi = mid;
  }

  const insertionIdx = offsets[lo] < target ? lo + 1 : lo;
  return Math.max(0, Math.min(offsets.length - 2, insertionIdx - 1));
}

export function useMeasuredVirtualList({
  itemCount,
  estimateHeight,
  viewportHeight,
  scrollTop,
  overscan = 4,
  measurementKey,
}: UseMeasuredVirtualListInput): UseMeasuredVirtualListResult {
  const safeItemCount = Number.isFinite(itemCount) ? Math.max(0, Math.floor(itemCount)) : 0;
  const safeEstimateHeight = Number.isFinite(estimateHeight) && estimateHeight > 0 ? estimateHeight : 1;
  const safeViewportHeight = Number.isFinite(viewportHeight) ? Math.max(0, viewportHeight) : 0;
  const safeScrollTop = Number.isFinite(scrollTop) ? Math.max(0, scrollTop) : 0;
  const safeOverscan = Number.isFinite(overscan) ? Math.max(0, Math.floor(overscan)) : 0;

  const [measurementState, setMeasurementState] = useState<MeasurementState>(() => ({
    key: measurementKey,
    heights: new Map(),
  }));
  const measuredHeights = Object.is(measurementState.key, measurementKey)
    ? measurementState.heights
    : EMPTY_MEASURED_HEIGHTS;

  useEffect(() => {
    setMeasurementState((prev) => {
      if (Object.is(prev.key, measurementKey)) return prev;

      return {
        key: measurementKey,
        heights: new Map(),
      };
    });
  }, [measurementKey]);

  const offsets = useMemo(
    () => buildOffsets(safeItemCount, safeEstimateHeight, measuredHeights),
    [safeEstimateHeight, safeItemCount, measuredHeights],
  );

  const totalHeight = offsets[safeItemCount] ?? 0;
  const rawStart = findIndexAtOffset(offsets, safeScrollTop);
  const rawEnd = findIndexBeforeOffset(offsets, safeScrollTop + safeViewportHeight);
  const startIdx = Math.max(0, rawStart - safeOverscan);
  const endIdx = Math.min(safeItemCount, rawEnd + safeOverscan + 1);
  const beforeHeight = offsets[startIdx] ?? 0;
  const afterHeight = Math.max(0, totalHeight - (offsets[endIdx] ?? totalHeight));

  const items = useMemo(
    () =>
      Array.from({ length: Math.max(0, endIdx - startIdx) }, (_, offset) => {
        const idx = startIdx + offset;
        const top = offsets[idx] ?? 0;

        return {
          idx,
          key: idx,
          top,
          height: (offsets[idx + 1] ?? top) - top,
        };
      }),
    [endIdx, offsets, startIdx],
  );

  const setMeasuredHeight = useCallback((idx: number, height: number) => {
    if (!Number.isFinite(idx) || !Number.isFinite(height) || height <= 0) return;

    const safeIdx = Math.floor(idx);
    if (safeIdx < 0 || safeIdx >= safeItemCount) return;

    setMeasurementState((prev) => {
      const prevHeights = Object.is(prev.key, measurementKey)
        ? prev.heights
        : EMPTY_MEASURED_HEIGHTS;

      if (Object.is(prev.key, measurementKey) && prevHeights.get(safeIdx) === height) return prev;

      const next = new Map(prevHeights);
      next.set(safeIdx, height);

      return {
        key: measurementKey,
        heights: next,
      };
    });
  }, [measurementKey, safeItemCount]);

  const scrollTopForIndex = useCallback(
    (idx: number) => {
      const safeIdx = Number.isFinite(idx) ? Math.max(0, Math.min(safeItemCount, Math.floor(idx))) : 0;
      return offsets[safeIdx] ?? 0;
    },
    [safeItemCount, offsets],
  );

  const indexFromScrollTop = useCallback((top: number) => findIndexAtOffset(offsets, top), [offsets]);

  return {
    startIdx,
    endIdx,
    beforeHeight,
    afterHeight,
    totalHeight,
    items,
    setMeasuredHeight,
    scrollTopForIndex,
    indexFromScrollTop,
  };
}
