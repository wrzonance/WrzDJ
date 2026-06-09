'use client';

/**
 * Minimal timeline list (#389) — ordered slot rows with BPM/key/energy
 * badges and bidirectional hover sync with the curve. Clicking a curve
 * block scrolls the matching row into view (only when out of view).
 * Full drag-reorder timeline lands with #390/#397.
 */

import { useEffect, useRef } from 'react';
import { fmtTime } from './curveMath';
import type { SlotView } from './types';
import { effectiveTarget } from './types';
import styles from './curve.module.css';

export interface ScrollRequest {
  idx: number;
  /** Monotonic nonce so repeated clicks on the same row re-trigger. */
  n: number;
}

export interface TimelinePanelProps {
  slots: SlotView[];
  hoveredIdx: number | null;
  onHover: (idx: number | null) => void;
  scrollRequest: ScrollRequest | null;
}

export default function TimelinePanel({
  slots,
  hoveredIdx,
  onHover,
  scrollRequest,
}: TimelinePanelProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);

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

  if (slots.length === 0) {
    return (
      <div className={styles.emptyState} data-testid="timeline-empty">
        No tracks in the set yet — fill from the pool to build the timeline.
      </div>
    );
  }

  return (
    <div className={styles.timelineList} ref={listRef} data-testid="timeline-list">
      {slots.map((s, i) => (
        <div
          key={s.id}
          ref={(el) => {
            rowRefs.current[i] = el;
          }}
          className={`${styles.timelineRow} ${hoveredIdx === i ? styles.timelineRowHover : ''}`}
          onMouseEnter={() => onHover(i)}
          onMouseLeave={() => onHover(null)}
          data-testid={`timeline-row-${i}`}
        >
          <span className={styles.timelinePos}>{String(i + 1).padStart(2, '0')}</span>
          <span className={styles.timelineTitle}>
            {s.track.title}
            {s.track.artist ? (
              <span className={styles.timelineArtist}> — {s.track.artist}</span>
            ) : null}
          </span>
          <span className={styles.timelineBadge}>{fmtTime(s.track.durationSec)}</span>
          <span className={styles.timelineBadge}>
            {s.track.bpm != null ? `${Math.round(s.track.bpm)} BPM` : '— BPM'}
          </span>
          <span className={styles.timelineBadge}>{s.track.key ?? '—'}</span>
          <span className={styles.timelineBadge}>e{s.track.energy}</span>
          <span className={styles.timelineTarget} title="Target energy">
            ◎ {effectiveTarget(s).toFixed(1)}
          </span>
        </div>
      ))}
    </div>
  );
}
