'use client';

import { type Dispatch, type DragEvent, type SetStateAction, useCallback } from 'react';
import { fmtTime } from './curveMath';
import { readPoolTrackDragPayload, SLOT_REORDER_DND_TYPE, writeSlotReorderDragPayload } from './dnd';
import { buildMovedIds } from './reorderMath';
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
  selected: boolean;
  dropIdx: number | null;
  setDropIdx: Dispatch<SetStateAction<number | null>>;
  onHover: (idx: number | null) => void;
  onRowDoubleClick?: (idx: number) => void;
  onPoolTrackDrop?: (poolTrackId: number, insertIdx: number) => void | Promise<void>;
  onSelectedChange: (selected: boolean) => void;
  onToggleLock?: () => void | Promise<void>;
  onMoveSlot?: (slotId: number, direction: 'up' | 'down') => void | Promise<void>;
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
  selected,
  dropIdx,
  setDropIdx,
  onHover,
  onRowDoubleClick,
  onPoolTrackDrop,
  onSelectedChange,
  onToggleLock,
  onMoveSlot,
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
  const dropWouldMoveLockedSlot = slots.some(
    (candidate, candidateIdx) => candidate.locked && candidateIdx >= idx,
  );
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
    if (dropWouldMoveLockedSlot) {
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
    if (dropWouldMoveLockedSlot) return;
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
        } ${dropIdx === idx ? styles.timelineRowDrop : ''} ${
          slot.locked ? styles.timelineRowLocked : ''
        }`}
        data-locked={slot.locked ? 'true' : 'false'}
        draggable={!slot.locked}
        onDragStart={(event) => {
          if (slot.locked) {
            event.preventDefault();
            return;
          }
          writeSlotReorderDragPayload(event.dataTransfer, slot.id);
        }}
        onMouseEnter={() => onHover(idx)}
        onMouseLeave={() => onHover(null)}
        onDoubleClick={() => onRowDoubleClick?.(idx)}
        onDragOver={(event) => {
          // Let slot-reorder drags bubble to the list's reorder handler — do
          // not consume them here (no stopPropagation, no preventDefault).
          if (event.dataTransfer.types?.includes(SLOT_REORDER_DND_TYPE)) return;
          event.stopPropagation();
          markPoolTrackDrop(event, idx);
        }}
        onDragLeave={clearDropIfLeaving}
        onDrop={(event) => {
          if (event.dataTransfer.types?.includes(SLOT_REORDER_DND_TYPE)) return;
          handlePoolTrackDrop(event, idx);
        }}
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
        <label
          className={styles.timelineSelect}
          title={`Select slot ${idx + 1}`}
          onClick={(event) => event.stopPropagation()}
          onDoubleClick={(event) => event.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={selected}
            aria-label={`Select slot ${idx + 1}`}
            data-testid={`timeline-select-${idx}`}
            onChange={(event) => onSelectedChange(event.currentTarget.checked)}
          />
        </label>
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
        {slot.locked ? (
          <span className={styles.timelineLockBadge} data-testid={`timeline-lock-badge-${idx}`}>
            <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M7 10V8a5 5 0 0 1 10 0v2M6.5 10h11a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 17.5 20h-11A1.5 1.5 0 0 1 5 18.5v-7A1.5 1.5 0 0 1 6.5 10Z"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.8"
              />
            </svg>
            Locked
          </span>
        ) : null}
        {!slot.locked && (
          <span className={styles.timelineMoveControls}>
            <button
              type="button"
              className={styles.timelineMoveBtn}
              draggable={false}
              aria-label={`Move ${slot.track.title} up`}
              title="Move up"
              disabled={buildMovedIds(slots, slot.id, 'up') === null}
              onClick={(event) => {
                event.stopPropagation();
                void onMoveSlot?.(slot.id, 'up');
              }}
              data-testid={`timeline-move-up-${idx}`}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor"
                  strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
              </svg>
            </button>
            <button
              type="button"
              className={styles.timelineMoveBtn}
              draggable={false}
              aria-label={`Move ${slot.track.title} down`}
              title="Move down"
              disabled={buildMovedIds(slots, slot.id, 'down') === null}
              onClick={(event) => {
                event.stopPropagation();
                void onMoveSlot?.(slot.id, 'down');
              }}
              data-testid={`timeline-move-down-${idx}`}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 5v14M5 12l7 7 7-7" fill="none" stroke="currentColor"
                  strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
              </svg>
            </button>
          </span>
        )}
        <button
          type="button"
          className={styles.timelineLockToggle}
          aria-label={`${slot.locked ? 'Unlock' : 'Lock'} slot ${idx + 1}`}
          title={`${slot.locked ? 'Unlock' : 'Lock'} slot ${idx + 1}`}
          onClick={(event) => {
            event.stopPropagation();
            void onToggleLock?.();
          }}
          data-testid={`timeline-lock-toggle-${idx}`}
        >
          {slot.locked ? (
            <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M8 10V8a4 4 0 0 1 7.6-1.8M6.5 10h11a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 17.5 20h-11A1.5 1.5 0 0 1 5 18.5v-7A1.5 1.5 0 0 1 6.5 10Z"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.8"
              />
            </svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M7 10V8a5 5 0 0 1 10 0v2M6.5 10h11a1.5 1.5 0 0 1 1.5 1.5v7A1.5 1.5 0 0 1 17.5 20h-11A1.5 1.5 0 0 1 5 18.5v-7A1.5 1.5 0 0 1 6.5 10Z"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.8"
              />
            </svg>
          )}
        </button>
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
