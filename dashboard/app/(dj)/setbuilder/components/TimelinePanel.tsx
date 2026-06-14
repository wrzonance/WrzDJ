'use client';

/**
 * Minimal timeline list (#389) — ordered slot rows with BPM/key/energy
 * badges and bidirectional hover sync with the curve. Clicking a curve
 * block scrolls the matching row into view (only when out of view).
 * Full drag-reorder timeline lands with #390/#397.
 */

import { useEffect, useRef, useState } from 'react';
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
  onPairingAction?: (idx: number) => void | Promise<void>;
}

export default function TimelinePanel({
  slots,
  hoveredIdx,
  onHover,
  scrollRequest,
  onPairingAction,
}: TimelinePanelProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [menu, setMenu] = useState<{ x: number; y: number; idx: number } | null>(null);

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

  if (slots.length === 0) {
    return (
      <div className={styles.emptyState} data-testid="timeline-empty">
        No tracks in the set yet — fill from the pool to build the timeline.
      </div>
    );
  }

  return (
    <div className={styles.timelineList} ref={listRef} data-testid="timeline-list">
      {slots.map((s, i) => {
        const prev = i > 0 ? slots[i - 1] : null;
        const seamScore = prev?.transitionScore ?? s.transitionScore;
        const isPairedSeam = Boolean(prev?.nextIsDjPairing);
        const pairingActionLabel = s.nextIsDjPairing
          ? `Open saved pairing after ${s.track.title}`
          : `Save ${s.track.title} into ${slots[i + 1]?.track.title ?? 'next track'} as pairing`;
        return (
          <div key={s.id} className={styles.timelineSlotGroup}>
            {i > 0 && (isPairedSeam || seamScore != null) && (
              <div
                className={`${styles.timelineTransition} ${
                  isPairedSeam ? styles.timelineTransitionPairing : ''
                }`}
                data-testid={`timeline-transition-${i - 1}`}
              >
                {seamScore != null && (
                  <span className={styles.timelineScoreChip}>{Math.round(seamScore)}</span>
                )}
                {isPairedSeam && (
                  <span className={styles.timelinePairingChip}>
                    <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
                      <path
                        d="M10.5 13.5 13.5 10.5M8.5 17.5H7.8a4.8 4.8 0 0 1 0-9.6h3.4M12.8 16.1h3.4a4.8 4.8 0 1 0 0-9.6h-.7"
                        fill="none"
                        stroke="currentColor"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="1.9"
                      />
                    </svg>
                    DJ pairing
                  </span>
                )}
              </div>
            )}
            <div
              ref={(el) => {
                rowRefs.current[i] = el;
              }}
              className={`${styles.timelineRow} ${hoveredIdx === i ? styles.timelineRowHover : ''}`}
              onMouseEnter={() => onHover(i)}
              onMouseLeave={() => onHover(null)}
              onContextMenu={(event) => {
                if (i >= slots.length - 1) return;
                event.preventDefault();
                setMenu({ x: event.clientX, y: event.clientY, idx: i });
              }}
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
              {i < slots.length - 1 && (
                <button
                  type="button"
                  className={styles.timelinePairingAction}
                  aria-label={pairingActionLabel}
                  title={pairingActionLabel}
                  onClick={(event) => {
                    event.stopPropagation();
                    const rect = event.currentTarget.getBoundingClientRect();
                    setMenu({ x: rect.left, y: rect.bottom + 4, idx: i });
                  }}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      d="M10.5 13.5 13.5 10.5M8.5 17.5H7.8a4.8 4.8 0 0 1 0-9.6h3.4M12.8 16.1h3.4a4.8 4.8 0 1 0 0-9.6h-.7"
                      fill="none"
                      stroke="currentColor"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="1.9"
                    />
                  </svg>
                </button>
              )}
            </div>
          </div>
        );
      })}
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
