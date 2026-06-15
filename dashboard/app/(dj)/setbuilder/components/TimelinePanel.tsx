'use client';

/**
 * Minimal timeline list (#389) — ordered slot rows with BPM/key/energy
 * badges and bidirectional hover sync with the curve. Clicking a curve
 * block scrolls the matching row into view (only when out of view).
 * Full drag-reorder timeline lands with #390/#397.
 */

import { type DragEvent, useEffect, useRef, useState } from 'react';
import { readPoolTrackDragPayload } from './dnd';
import TimelineRow, { type TimelineMenu } from './TimelineRow';
import type { SlotView } from './types';
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
  const [menu, setMenu] = useState<TimelineMenu | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);

  useEffect(() => {
    if (!scrollRequest || !listRef.current) return;
    const row = rowRefs.current[scrollRequest.idx];
    if (!row) return;
    const list = listRef.current.getBoundingClientRect();
    const r = row.getBoundingClientRect();
    const outOfView = r.top < list.top || r.bottom > list.bottom;
    if (outOfView) {
      row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [scrollRequest]);

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
      onDragOver={(event) => markPoolTrackDrop(event, slots.length)}
      onDragLeave={clearDropIfLeaving}
      onDrop={(event) => handlePoolTrackDrop(event, slots.length)}
    >
      {slots.map((slot, idx) => (
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
        />
      ))}
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
