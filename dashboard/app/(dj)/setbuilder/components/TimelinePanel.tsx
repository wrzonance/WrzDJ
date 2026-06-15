'use client';

/**
 * Minimal timeline list (#389) — ordered slot rows with BPM/key/energy
 * badges and bidirectional hover sync with the curve. Clicking a curve
 * block scrolls the matching row into view, including virtualized rows.
 * Full drag-reorder timeline lands with #390/#397.
 */

import {
  type DragEvent,
  type UIEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { readPoolTrackDragPayload } from './dnd';
import TimelineRow, { type TimelineMenu } from './TimelineRow';
import type { SlotView } from './types';
import { useMeasuredVirtualList } from './useMeasuredVirtualList';
import styles from './curve.module.css';

export interface ScrollRequest {
  idx: number;
  /** Monotonic nonce so repeated clicks on the same row re-trigger. */
  n: number;
}

export interface TimelinePanelProps {
  slots: SlotView[];
  hoveredIdx: number | null;
  currentIdx: number;
  positionSec: number;
  playing: boolean;
  onHover: (idx: number | null) => void;
  onRowDoubleClick?: (idx: number) => void;
  scrollRequest: ScrollRequest | null;
  onPairingAction?: (idx: number) => void | Promise<void>;
  onPoolTrackDrop?: (poolTrackId: number, insertIdx: number) => void | Promise<void>;
}

const ESTIMATED_SLOT_GROUP_HEIGHT = 52;
const TIMELINE_OVERSCAN_ROWS = 8;

export function timelineMeasurementKey(slots: SlotView[]): string {
  return slots
    .map((slot) =>
      [
        slot.id,
        slot.transitionScore ?? '',
        slot.nextIsDjPairing ? 1 : 0,
      ].join(','),
    )
    .join(':');
}

export default function TimelinePanel({
  slots,
  hoveredIdx,
  currentIdx,
  positionSec,
  playing,
  onHover,
  onRowDoubleClick,
  scrollRequest,
  onPairingAction,
  onPoolTrackDrop,
}: TimelinePanelProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);
  const handledScrollRequestNRef = useRef<number | null>(null);
  const [menu, setMenu] = useState<TimelineMenu | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);

  const measurementKey = useMemo(() => timelineMeasurementKey(slots), [slots]);
  const virtual = useMeasuredVirtualList({
    itemCount: slots.length,
    estimateHeight: ESTIMATED_SLOT_GROUP_HEIGHT,
    viewportHeight,
    scrollTop,
    overscan: TIMELINE_OVERSCAN_ROWS,
    measurementKey,
  });
  const {
    afterHeight,
    beforeHeight,
    indexFromScrollTop,
    items,
    scrollTopForIndex,
    setMeasuredHeight,
    totalHeight,
  } = virtual;

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;

    const measure = () => {
      setViewportHeight(list.clientHeight || list.getBoundingClientRect().height || 0);
    };

    measure();

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }

    const observer = new ResizeObserver(measure);
    observer.observe(list);
    return () => observer.disconnect();
  }, [slots.length]);

  useEffect(() => {
    if (!scrollRequest || !listRef.current) return;
    if (handledScrollRequestNRef.current === scrollRequest.n) return;
    if (scrollRequest.idx < 0 || scrollRequest.idx >= slots.length) return;
    handledScrollRequestNRef.current = scrollRequest.n;

    const list = listRef.current;
    const row = rowRefs.current[scrollRequest.idx];
    const listRect = row ? list.getBoundingClientRect() : null;
    const rowRect = row ? row.getBoundingClientRect() : null;
    const rowTop =
      rowRect && listRect
        ? list.scrollTop + rowRect.top - listRect.top
        : scrollTopForIndex(scrollRequest.idx);
    const rowBottom =
      rowRect && listRect
        ? list.scrollTop + rowRect.bottom - listRect.top
        : scrollTopForIndex(scrollRequest.idx + 1);
    const rowHeight = Math.max(1, rowBottom - rowTop);
    const visibleTop = list.scrollTop;
    const visibleHeight =
      viewportHeight || list.clientHeight || list.getBoundingClientRect().height || rowHeight;
    const visibleBottom = visibleTop + visibleHeight;
    let nextScrollTop = visibleTop;

    if (rowTop < visibleTop) {
      nextScrollTop = rowTop;
    } else if (rowBottom > visibleBottom) {
      nextScrollTop = Math.max(0, rowBottom - visibleHeight);
    }

    list.scrollTop = nextScrollTop;
    setScrollTop(nextScrollTop);
  }, [scrollRequest, scrollTopForIndex, slots.length, viewportHeight]);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener('click', close);
    window.addEventListener('keydown', close);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('keydown', close);
    };
  }, [menu]);

  const measureSlotGroup = useCallback(
    (idx: number, el: HTMLDivElement | null) => {
      if (!el) return;
      setMeasuredHeight(idx, el.offsetHeight || el.getBoundingClientRect().height);
    },
    [setMeasuredHeight],
  );

  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    setScrollTop(event.currentTarget.scrollTop);
  };

  const insertIndexFromPointer = (event: DragEvent<HTMLElement>) => {
    const list = listRef.current;
    if (!list) return slots.length;

    const rect = list.getBoundingClientRect();
    const pointerTop = event.clientY - rect.top + list.scrollTop;
    const insertIdx =
      pointerTop >= totalHeight ? slots.length : indexFromScrollTop(pointerTop);

    return Math.max(0, Math.min(slots.length, insertIdx));
  };

  const markPoolTrackDrop = (event: DragEvent<HTMLElement>, insertIdx: number) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    setDropIdx(insertIdx);
  };

  const handlePoolTrackDrop = (event: DragEvent<HTMLElement>, insertIdx: number) => {
    event.preventDefault();
    event.stopPropagation();
    setDropIdx(null);
    const payload = readPoolTrackDragPayload(event.dataTransfer);
    if (!payload) return;
    void onPoolTrackDrop?.(payload.poolTrackId, insertIdx);
  };

  const markPoolTrackDropAtPointer = (event: DragEvent<HTMLElement>) => {
    markPoolTrackDrop(event, insertIndexFromPointer(event));
  };

  const handlePoolTrackDropAtPointer = (event: DragEvent<HTMLElement>) => {
    handlePoolTrackDrop(event, insertIndexFromPointer(event));
  };

  const clearDropIfLeaving = (event: DragEvent<HTMLElement>) => {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
    setDropIdx(null);
  };

  if (slots.length === 0) {
    return (
      <div
        className={`${styles.emptyState} ${dropIdx === 0 ? styles.timelineListDrop : ''}`}
        data-testid="timeline-empty"
        onDragOver={(event) => markPoolTrackDrop(event, 0)}
        onDragLeave={clearDropIfLeaving}
        onDrop={(event) => handlePoolTrackDrop(event, 0)}
      >
        No tracks in the set yet — fill from the pool to build the timeline.
      </div>
    );
  }

  return (
    <div
      className={`${styles.timelineList} ${dropIdx === slots.length ? styles.timelineListDrop : ''}`}
      ref={listRef}
      data-testid="timeline-list"
      data-virtualized="true"
      onScroll={handleScroll}
      onDragOver={markPoolTrackDropAtPointer}
      onDragLeave={clearDropIfLeaving}
      onDrop={handlePoolTrackDropAtPointer}
    >
      <div style={{ height: beforeHeight }} aria-hidden="true" />
      {items.map(({ idx }) => {
        const slot = slots[idx];
        if (!slot) return null;

        return (
          <TimelineRow
            key={slot.id}
            slot={slot}
            prevSlot={idx > 0 ? slots[idx - 1] : null}
            nextSlot={idx < slots.length - 1 ? slots[idx + 1] : null}
            idx={idx}
            slots={slots}
            hoveredIdx={hoveredIdx}
            currentIdx={currentIdx}
            positionSec={positionSec}
            playing={playing}
            dropIdx={dropIdx}
            setDropIdx={setDropIdx}
            onHover={onHover}
            onRowDoubleClick={onRowDoubleClick}
            onPoolTrackDrop={onPoolTrackDrop}
            setMenu={setMenu}
            setRowRef={(rowIdx, el) => {
              rowRefs.current[rowIdx] = el;
            }}
            measureRef={measureSlotGroup}
          />
        );
      })}
      <div style={{ height: afterHeight }} aria-hidden="true" />
      {menu && (
        <div
          className={styles.timelineContextMenu}
          style={{ left: menu.x, top: menu.y }}
          onClick={(event) => event.stopPropagation()}
          data-testid="timeline-context-menu"
        >
          <button
            type="button"
            className={styles.timelineContextItem}
            onClick={() => {
              onPairingAction?.(menu.idx);
              setMenu(null);
            }}
          >
            {slots[menu.idx]?.nextIsDjPairing
              ? 'Open saved pairing'
              : `Save -> ${slots[menu.idx + 1]?.track.title ?? 'next'} as pairing`}
          </button>
        </div>
      )}
    </div>
  );
}
