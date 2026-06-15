'use client';

import { type Dispatch, type DragEvent, type SetStateAction, useCallback } from 'react';
import { fmtTime } from './curveMath';
import { readPoolTrackDragPayload } from './dnd';
import { localPositionSec } from './transportMath';
import type { SlotView } from './types';
import { effectiveTarget } from './types';
import styles from './curve.module.css';

export interface TimelineMenu {
  x: number;
  y: number;
  idx: number;
}

export interface TimelineRowProps {
  slot: SlotView;
  prevSlot: SlotView | null;
  nextSlot: SlotView | null;
  idx: number;
  slots: SlotView[];
  hoveredIdx: number | null;
  currentIdx: number;
  positionSec: number;
  playing: boolean;
  dropIdx: number | null;
  setDropIdx: Dispatch<SetStateAction<number | null>>;
  onHover: (idx: number | null) => void;
  onRowDoubleClick?: (idx: number) => void;
  onPoolTrackDrop?: (poolTrackId: number, insertIdx: number) => void | Promise<void>;
  setMenu: Dispatch<SetStateAction<TimelineMenu | null>>;
  setRowRef?: (idx: number, el: HTMLDivElement | null) => void;
  measureRef?: (idx: number, el: HTMLDivElement | null) => void;
}

export default function TimelineRow({
  slot,
  prevSlot,
  nextSlot,
  idx,
  slots,
  hoveredIdx,
  currentIdx,
  positionSec,
  playing,
  dropIdx,
  setDropIdx,
  onHover,
  onRowDoubleClick,
  onPoolTrackDrop,
  setMenu,
  setRowRef,
  measureRef,
}: TimelineRowProps) {
  const seamScore = prevSlot?.transitionScore ?? slot.transitionScore;
  const isPairedSeam = Boolean(prevSlot?.nextIsDjPairing);
  const isCurrent = currentIdx === idx;
  const progress =
    isCurrent && slot.track.durationSec > 0
      ? Math.min(
          100,
          Math.max(
            0,
            (localPositionSec(slots, idx, positionSec) / slot.track.durationSec) * 100,
          ),
        )
      : 0;
  const pairingActionLabel = slot.nextIsDjPairing
    ? `Open saved pairing after ${slot.track.title}`
    : `Save ${slot.track.title} into ${nextSlot?.track.title ?? 'next track'} as pairing`;
  const handleMeasureRef = useCallback(
    (el: HTMLDivElement | null) => {
      measureRef?.(idx, el);
    },
    [idx, measureRef],
  );
  const handleRowRef = useCallback(
    (el: HTMLDivElement | null) => {
      setRowRef?.(idx, el);
    },
    [idx, setRowRef],
  );

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

  return (
    <div className={styles.timelineSlotGroup} ref={handleMeasureRef}>
      {idx > 0 && (isPairedSeam || seamScore != null) && (
        <div
          className={`${styles.timelineTransition} ${
            isPairedSeam ? styles.timelineTransitionPairing : ''
          }`}
          data-testid={`timeline-transition-${idx - 1}`}
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
        ref={handleRowRef}
        className={`${styles.timelineRow} ${hoveredIdx === idx ? styles.timelineRowHover : ''} ${
          isCurrent ? styles.timelineRowNow : ''
        } ${dropIdx === idx ? styles.timelineRowDrop : ''}`}
        onMouseEnter={() => onHover(idx)}
        onMouseLeave={() => onHover(null)}
        onDoubleClick={() => onRowDoubleClick?.(idx)}
        onDragOver={(event) => {
          event.stopPropagation();
          markPoolTrackDrop(event, idx);
        }}
        onDragLeave={clearDropIfLeaving}
        onDrop={(event) => handlePoolTrackDrop(event, idx)}
        onContextMenu={(event) => {
          if (idx >= slots.length - 1) return;
          event.preventDefault();
          setMenu({ x: event.clientX, y: event.clientY, idx });
        }}
        data-testid={`timeline-row-${idx}`}
      >
        {isCurrent ? (
          <span
            className={styles.timelineRowProgress}
            style={{ width: `${progress}%` }}
            aria-hidden="true"
          />
        ) : null}
        <span className={styles.timelinePos}>
          {isCurrent ? (
            playing ? (
              <span
                className={`${styles.rowVu} ${styles.rowVuActive}`}
                data-testid={`timeline-vu-${idx}`}
              >
                <span />
                <span />
                <span />
                <span />
              </span>
            ) : (
              <span className={styles.timelinePauseIcon} data-testid={`timeline-pause-${idx}`}>
                <span />
                <span />
              </span>
            )
          ) : (
            String(idx + 1).padStart(2, '0')
          )}
        </span>
        <span className={styles.timelineTitle}>
          {slot.track.title}
          {slot.track.artist ? (
            <span className={styles.timelineArtist}> — {slot.track.artist}</span>
          ) : null}
        </span>
        <span className={styles.timelineBadge}>{fmtTime(slot.track.durationSec)}</span>
        <span className={styles.timelineBadge}>
          {slot.track.bpm != null ? `${Math.round(slot.track.bpm)} BPM` : '— BPM'}
        </span>
        <span className={styles.timelineBadge}>{slot.track.key ?? '—'}</span>
        <span className={styles.timelineBadge}>e{slot.track.energy}</span>
        <span className={styles.timelineTarget} title="Target energy">
          ◎ {effectiveTarget(slot).toFixed(1)}
        </span>
        {idx < slots.length - 1 && (
          <button
            type="button"
            className={styles.timelinePairingAction}
            aria-label={pairingActionLabel}
            title={pairingActionLabel}
            onClick={(event) => {
              event.stopPropagation();
              const rect = event.currentTarget.getBoundingClientRect();
              setMenu({ x: rect.left, y: rect.bottom + 4, idx });
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
}
