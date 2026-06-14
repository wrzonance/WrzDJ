'use client';

import { fmtTime } from './curveMath';
import { localPositionSec, totalDuration } from './transportMath';
import type { SlotView } from './types';
import styles from './curve.module.css';

interface TransportStatus {
  connected: boolean;
  active_source: string | null;
  device_name: string | null;
}

interface TransportBarProps {
  slots: SlotView[];
  currentIdx: number;
  positionSec: number;
  playing: boolean;
  status: TransportStatus;
  onPrev: () => void;
  onToggle: () => void;
  onNext: () => void;
}

function VuMeter({ playing }: { playing: boolean }) {
  return (
    <span className={`${styles.vuMeter} ${playing ? styles.vuMeterActive : ''}`} aria-hidden="true">
      {[0, 1, 2, 3].map((i) => (
        <span key={i} />
      ))}
    </span>
  );
}

function Icon({ name }: { name: 'prev' | 'play' | 'pause' | 'next' }) {
  if (name === 'prev') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M6 5h2v14H6zM9 12l9-7v14z" />
      </svg>
    );
  }
  if (name === 'next') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M16 5h2v14h-2zM6 5l9 7-9 7z" />
      </svg>
    );
  }
  if (name === 'pause') {
    return (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M7 5h4v14H7zM13 5h4v14h-4z" />
      </svg>
    );
  }
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

export default function TransportBar({
  slots,
  currentIdx,
  positionSec,
  playing,
  status,
  onPrev,
  onToggle,
  onNext,
}: TransportBarProps) {
  const totalSec = totalDuration(slots);
  const current = slots[currentIdx] ?? null;
  const localElapsed = current ? localPositionSec(slots, currentIdx, positionSec) : 0;
  const progressPct = totalSec > 0 ? Math.min(100, Math.max(0, (positionSec / totalSec) * 100)) : 0;
  const source = status.active_source?.replace(/^setbuilder:/, '') ?? 'tidal';
  const slotLabel = current ? String(currentIdx + 1).padStart(2, '0') : '--';
  const meta = current
    ? [
        current.track.artist || 'Unknown artist',
        current.track.bpm != null ? `${Math.round(current.track.bpm)} BPM` : '-- BPM',
        current.track.key ?? '--',
      ].join(' · ')
    : 'Bridge playback is idle';

  return (
    <section className={styles.transportBar} aria-label="Transport" data-testid="transport-bar">
      <div className={styles.transportProgress} aria-hidden="true">
        <span style={{ width: `${progressPct}%` }} />
      </div>
      <div className={styles.transportControls}>
        <button type="button" className={styles.transportBtn} onClick={onPrev} aria-label="Previous track">
          <Icon name="prev" />
        </button>
        <button
          type="button"
          className={`${styles.transportBtn} ${styles.transportPlayBtn}`}
          onClick={onToggle}
          aria-label={playing ? 'Pause' : 'Play'}
          disabled={slots.length === 0}
        >
          <Icon name={playing ? 'pause' : 'play'} />
        </button>
        <button type="button" className={styles.transportBtn} onClick={onNext} aria-label="Next track">
          <Icon name="next" />
        </button>
      </div>

      <div className={styles.nowPlayingReadout}>
        <div className={styles.artTile}>{current ? current.track.title.slice(0, 1).toUpperCase() : '-'}</div>
        <div className={styles.nowPlayingText}>
          <div className={styles.nowTitle}>
            <VuMeter playing={playing} />
            <span className={styles.slotChip}>Slot {slotLabel}</span>
            <span className={styles.nowTitleText}>{current?.track.title ?? 'No track loaded'}</span>
          </div>
          <div className={styles.nowMeta}>{meta}</div>
        </div>
      </div>

      <div className={styles.transportTimes}>
        <span className={styles.transportTimePrimary}>
          {fmtTime(localElapsed)} / {fmtTime(current?.track.durationSec ?? 0)}
        </span>
        <span className={styles.transportTimeDivider} aria-hidden="true" />
        <span className={styles.transportTimeSet}>
          {fmtTime(positionSec)} / {fmtTime(totalSec)}
        </span>
      </div>

      <div
        className={`${styles.bridgePill} ${status.connected ? styles.bridgePillOn : styles.bridgePillOff}`}
        title={status.device_name ?? undefined}
      >
        <span className={styles.bridgeDot} aria-hidden="true" />
        <span className={styles.bridgeText}>
          <span>Bridge {status.connected ? 'online' : 'offline'}</span>
          <span>{source}</span>
        </span>
      </div>
    </section>
  );
}
