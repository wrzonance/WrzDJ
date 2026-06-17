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
import { readPoolTrackDragPayload, readSlotReorderDragPayload, SLOT_REORDER_DND_TYPE } from './dnd';
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
  onSlotLockChange?: (slotIds: number[], locked: boolean) => void | Promise<void>;
  onLockBeforePlayhead?: () => void | Promise<void>;
  onSlotReorder?: (slotId: number, insertIdx: number) => void | Promise<void>;
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
  onSlotLockChange,
  onLockBeforePlayhead,
  onSlotReorder,
}: TimelinePanelProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);
  const handledScrollRequestNRef = useRef<number | null>(null);
  const reorderSourceRef = useRef<number | null>(null);
  const [menu, setMenu] = useState<TimelineMenu | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);
  const selectedSlotIds = useMemo(() => [...selectedIds], [selectedIds]);
  const selectedCount = selectedIds.size;
  const slotsBeforePlayhead = useMemo(() => {
    let startSec = 0;
    const ids: number[] = [];
    for (const slot of slots) {
      if (startSec < positionSec && !slot.locked) ids.push(slot.id);
      startSec += slot.track.durationSec;
    }
    return ids;
  }, [positionSec, slots]);

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

  useEffect(() => {
    const visibleIds = new Set(slots.map((slot) => slot.id));
    setSelectedIds((prev) => {
      const next = new Set([...prev].filter((id) => visibleIds.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [slots]);

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
    if (!Number.isFinite(pointerTop)) return slots.length;
    const insertIdx =
      pointerTop >= totalHeight ? slots.length : indexFromScrollTop(pointerTop);

    return Math.max(0, Math.min(slots.length, insertIdx));
  };

  const markPoolTrackDrop = (event: DragEvent<HTMLElement>, insertIdx: number) => {
    event.preventDefault();
    if (slots.some((slot, idx) => slot.locked && idx >= insertIdx)) {
      event.dataTransfer.dropEffect = 'none';
      setDropIdx(null);
      return;
    }
    event.dataTransfer.dropEffect = 'copy';
    setDropIdx(insertIdx);
  };

  const handlePoolTrackDrop = (event: DragEvent<HTMLElement>, insertIdx: number) => {
    event.preventDefault();
    event.stopPropagation();
    setDropIdx(null);
    if (slots.some((slot, idx) => slot.locked && idx >= insertIdx)) return;
    const payload = readPoolTrackDragPayload(event.dataTransfer);
    if (!payload) return;
    void onPoolTrackDrop?.(payload.poolTrackId, insertIdx);
  };

  const setSlotSelected = (slotId: number, selected: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (selected) next.add(slotId);
      else next.delete(slotId);
      return next;
    });
  };

  const clearSelection = () => setSelectedIds(new Set());

  const changeSelectedLock = (locked: boolean) => {
    if (selectedSlotIds.length === 0) return;
    void onSlotLockChange?.(selectedSlotIds, locked);
    clearSelection();
  };

  const markPoolTrackDropAtPointer = (event: DragEvent<HTMLElement>) => {
    markPoolTrackDrop(event, insertIndexFromPointer(event));
  };

  const handlePoolTrackDropAtPointer = (event: DragEvent<HTMLElement>) => {
    handlePoolTrackDrop(event, insertIndexFromPointer(event));
  };

  const dragIsReorder = (event: DragEvent<HTMLElement>) =>
    event.dataTransfer.types.includes(SLOT_REORDER_DND_TYPE);

  const reorderWouldCrossLock = (fromIdx: number, insertIdx: number) => {
    const target = insertIdx > fromIdx ? insertIdx - 1 : insertIdx;
    const lo = Math.min(fromIdx, target);
    const hi = Math.max(fromIdx, target);
    return slots.some((s, i) => s.locked && i !== fromIdx && i >= lo && i <= hi);
  };

  const handleListDragStart = (event: DragEvent<HTMLElement>) => {
    const payload = readSlotReorderDragPayload(event.dataTransfer);
    reorderSourceRef.current = payload ? payload.slotId : null;
  };

  const clearReorderSource = () => {
    reorderSourceRef.current = null;
  };

  const resolveReorder = (event: DragEvent<HTMLElement>) => {
    const slotId = reorderSourceRef.current;
    const fromIdx = slotId == null ? -1 : slots.findIndex((s) => s.id === slotId);
    const insertIdx = insertIndexFromPointer(event);
    const valid = fromIdx >= 0 && !reorderWouldCrossLock(fromIdx, insertIdx);
    return { slotId, insertIdx, valid };
  };

  const markReorderDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const { insertIdx, valid } = resolveReorder(event);
    if (!valid) {
      event.dataTransfer.dropEffect = 'none';
      setDropIdx(null);
      return;
    }
    event.dataTransfer.dropEffect = 'move';
    setDropIdx(insertIdx);
  };

  const handleReorderDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDropIdx(null);
    const { slotId, insertIdx, valid } = resolveReorder(event);
    clearReorderSource();
    if (!valid || slotId == null) return;
    void onSlotReorder?.(slotId, insertIdx);
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
    <>
      <div className={styles.timelineBulkBar} data-testid="timeline-lock-toolbar">
        <span className={styles.timelineBulkCount}>
          {selectedCount > 0 ? `${selectedCount} selected` : 'No selection'}
        </span>
        <button
          type="button"
          className={styles.timelineBulkBtn}
          onClick={() => changeSelectedLock(true)}
          disabled={selectedCount === 0}
          data-testid="timeline-lock-selected"
        >
          Lock selected
        </button>
        <button
          type="button"
          className={styles.timelineBulkBtn}
          onClick={() => changeSelectedLock(false)}
          disabled={selectedCount === 0}
          data-testid="timeline-unlock-selected"
        >
          Unlock selected
        </button>
        <button
          type="button"
          className={styles.timelineBulkBtn}
          onClick={() => void onLockBeforePlayhead?.()}
          disabled={slotsBeforePlayhead.length === 0}
          data-testid="timeline-lock-before-playhead"
          title="Lock every unlocked slot whose start time is before the playhead"
        >
          Lock before playhead
        </button>
      </div>
      <div
        className={`${styles.timelineList} ${dropIdx === slots.length ? styles.timelineListDrop : ''}`}
        ref={listRef}
        data-testid="timeline-list"
        data-virtualized="true"
        onScroll={handleScroll}
        onDragStart={handleListDragStart}
        onDragEnd={clearReorderSource}
        onDragOver={(event) =>
          dragIsReorder(event) ? markReorderDrop(event) : markPoolTrackDropAtPointer(event)
        }
        onDragLeave={clearDropIfLeaving}
        onDrop={(event) =>
          dragIsReorder(event) ? handleReorderDrop(event) : handlePoolTrackDropAtPointer(event)
        }
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
              selected={selectedIds.has(slot.id)}
              dropIdx={dropIdx}
              setDropIdx={setDropIdx}
              onHover={onHover}
              onRowDoubleClick={onRowDoubleClick}
              onPoolTrackDrop={onPoolTrackDrop}
              onSelectedChange={(selected) => setSlotSelected(slot.id, selected)}
              onToggleLock={() => void onSlotLockChange?.([slot.id], !slot.locked)}
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
    </>
  );
}
