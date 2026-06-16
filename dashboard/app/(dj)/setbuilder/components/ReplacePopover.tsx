'use client';

/**
 * Replacement popover (#389) — surfaces after a drag-release when a slot's
 * target energy diverges from the track's intrinsic energy by ≥ 0.8.
 * Lists the top-5 pool candidates ranked by energy match + BPM continuity +
 * Camelot adjacency. Candidates come in via props (pool lands with #388).
 */

import type { ReplacementCandidate } from './curveMath';
import type { SlotView } from './types';
import styles from './curve.module.css';

export interface ReplacePrompt {
  slotIdx: number;
  targetEnergy: number;
  anchorX: number;
  anchorY: number;
}

export interface ReplacePopoverProps {
  prompt: ReplacePrompt;
  slot: SlotView;
  candidates: ReplacementCandidate[];
  onReplace: (slotId: number, trackId: string) => void;
  onKeep: () => void;
  onDismiss: () => void;
}

export default function ReplacePopover({
  prompt,
  slot,
  candidates,
  onReplace,
  onKeep,
  onDismiss,
}: ReplacePopoverProps) {
  const cur = slot.track;
  const target = prompt.targetEnergy;
  const dir = target - cur.energy > 0 ? 'higher' : 'lower';
  const replacementDisabled = slot.locked;

  return (
    <>
      <div className={styles.popoverBackdrop} onClick={onDismiss} data-testid="replace-backdrop" />
      <div
        className={styles.popover}
        role="dialog"
        aria-label="Find replacement track"
        data-testid="replace-popover"
        style={{
          left: Math.max(12, Math.min(prompt.anchorX, window.innerWidth - 372)),
          top: Math.max(12, Math.min(prompt.anchorY + 12, window.innerHeight - 320)),
        }}
      >
        <div className={styles.popoverHeader}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className={styles.popoverEyebrow}>
              Slot {String(prompt.slotIdx + 1).padStart(2, '0')} · energy retarget
            </div>
            <div className={styles.popoverTitle}>
              <span>{cur.energy.toFixed(0)}</span>
              <span aria-hidden>→</span>
              <span className={styles.popoverTarget}>{target.toFixed(1)}</span>
              <span className={styles.popoverEyebrow}>target</span>
            </div>
            <div className={styles.popoverSub}>
              &ldquo;{cur.title}&rdquo; is energy {cur.energy} — you&rsquo;ve dialed the target{' '}
              {dir}.{' '}
              {replacementDisabled
                ? 'Replacement was skipped because locked slots are protected.'
                : 'Replace with a track that fits?'}
            </div>
          </div>
          <button className="btn btn-sm" onClick={onDismiss} title="Keep current track">
            ✕
          </button>
        </div>

        {replacementDisabled && (
          <div className={styles.popoverLocked} data-testid="replace-locked">
            Skipped because this slot is locked. Unlock the slot before replacing its track.
          </div>
        )}

        {candidates.length === 0 && (
          <div className={styles.popoverEmpty} data-testid="replace-empty">
            No pool tracks within ±2.5 of energy {target.toFixed(1)}. Import tracks into the pool
            or try the agent chat for a creative pick.
          </div>
        )}

        <div>
          {candidates.map((c) => (
            <button
              key={c.track.id}
              className={`${styles.candidate} ${
                replacementDisabled ? styles.candidateDisabled : ''
              }`}
              onClick={() => {
                if (!replacementDisabled) onReplace(slot.id, c.track.id);
              }}
              disabled={replacementDisabled}
              data-testid={`replace-candidate-${c.track.id}`}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className={styles.candidateTitle}>{c.track.title}</div>
                <div className={styles.candidateArtist}>{c.track.artist}</div>
              </div>
              <span className={styles.candidateMeta}>
                {c.track.bpm != null ? `${Math.round(c.track.bpm)} BPM` : '— BPM'} ·{' '}
                {c.track.key ?? '—'} · e{c.track.energy}
              </span>
              <span className={styles.candidateScore} title="Composite fit (energy + BPM + Camelot)">
                {Math.round(c.score * 100)}
              </span>
            </button>
          ))}
        </div>

        <div className={styles.popoverFooter}>
          <button className="btn btn-sm" onClick={onKeep} data-testid="replace-keep">
            Keep &ldquo;{cur.title}&rdquo; anyway
          </button>
          <button className="btn btn-sm" onClick={onDismiss}>
            Cancel
          </button>
        </div>
      </div>
    </>
  );
}
