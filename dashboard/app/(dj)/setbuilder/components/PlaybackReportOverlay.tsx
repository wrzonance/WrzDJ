'use client';

import { useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api';
import type { PlaybackReport, PlaybackSlotOutcome, PlaybackUnplannedPlay } from '@/lib/api/types';

import playbackStyles from '../setbuilder-playback.module.css';
import pairingStyles from '../setbuilder-pairings.module.css';
import sharedStyles from '../setbuilder-shared.module.css';

type Outcome = PlaybackSlotOutcome['outcome'];

interface PlaybackReportOverlayProps {
  setId: number;
  open: boolean;
  onClose: () => void;
  /** Notified with the bumped count after an apply succeeds. */
  onApplied?: (bumped: number) => void;
}

const OUTCOME_LABEL: Record<Outcome, string> = {
  played: 'Played',
  out_of_order: 'Out of order',
  skipped: 'Skipped',
  substituted: 'Unplanned',
};

const OUTCOME_CLASS: Record<Outcome, string> = {
  played: playbackStyles.outcomePlayed,
  out_of_order: playbackStyles.outcomeOutOfOrder,
  skipped: playbackStyles.outcomeSkipped,
  substituted: playbackStyles.outcomeSubstituted,
};

/** One ordered chronological item: a played planned slot OR an unplanned play. */
type TimelineItem =
  | { kind: 'slot'; order: number; slot: PlaybackSlotOutcome }
  | { kind: 'unplanned'; order: number; play: PlaybackUnplannedPlay };

function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return (
    <span className={`${playbackStyles.outcomeBadge} ${OUTCOME_CLASS[outcome]}`}>
      {OUTCOME_LABEL[outcome]}
    </span>
  );
}

function ReportIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M4 19V5m0 14h16M8 16V9m4 7V6m4 10v-4"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

export default function PlaybackReportOverlay({
  setId,
  open,
  onClose,
  onApplied,
}: PlaybackReportOverlayProps) {
  const [report, setReport] = useState<PlaybackReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setReport(null);
    setError(null);
    setApplyResult(null);
    api
      .getPlaybackReport(setId)
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch(() => {
        if (!cancelled) setError('Playback report failed to load.');
      });
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      cancelled = true;
      document.removeEventListener('keydown', onKey);
    };
  }, [open, setId, onClose]);

  // Played + out-of-order slots and unplanned plays, interleaved by actual play order.
  const timeline = useMemo<TimelineItem[]>(() => {
    if (!report) return [];
    const items: TimelineItem[] = [];
    for (const slot of report.slots) {
      if (slot.play_order != null) items.push({ kind: 'slot', order: slot.play_order, slot });
    }
    for (const play of report.unplanned) {
      items.push({ kind: 'unplanned', order: play.play_order, play });
    }
    return items.sort((a, b) => a.order - b.order);
  }, [report]);

  const skipped = useMemo(
    () => (report ? report.slots.filter((s) => s.play_order == null) : []),
    [report],
  );

  if (!open) return null;

  const summary = report?.summary;

  const applyPairings = async () => {
    setApplying(true);
    setApplyResult(null);
    try {
      const result = await api.applyPlaybackPairings(setId);
      setApplyResult(
        result.bumped > 0
          ? `Bumped ${result.bumped} pairing${result.bumped === 1 ? '' : 's'} from real plays.`
          : 'No back-to-back curated transitions were played — nothing to bump.',
      );
      onApplied?.(result.bumped);
    } catch {
      setApplyResult('Failed to apply pairings.');
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className={pairingStyles.pairingsWrap}>
      <button
        type="button"
        className={pairingStyles.pairingsBackdrop}
        aria-label="Close playback report"
        onClick={onClose}
      />
      <div
        className={pairingStyles.pairingsShell}
        role="dialog"
        aria-modal="true"
        aria-labelledby="playback-report-title"
      >
        <header className={pairingStyles.pairingsHeader}>
          <div className={pairingStyles.pairingsIcon}>
            <ReportIcon />
          </div>
          <div className={pairingStyles.pairingsHeaderText}>
            <h2 id="playback-report-title">Playback report</h2>
            <p>What you planned vs. what actually played at the event.</p>
          </div>
          {summary && (
            <div className={pairingStyles.pairingsStats}>
              <span>
                <strong>{summary.played}</strong> played
              </span>
              <span>
                <strong>{summary.out_of_order}</strong> reordered
              </span>
              <span>
                <strong>{summary.skipped}</strong> skipped
              </span>
              <span>
                <strong>{summary.unplanned}</strong> unplanned
              </span>
            </div>
          )}
          <button type="button" className={sharedStyles.iconBtn} onClick={onClose} aria-label="Close">
            x
          </button>
        </header>

        <div className={playbackStyles.playbackBody}>
          {error && <div className={sharedStyles.imError}>{error}</div>}
          {!error && !report && <div className={pairingStyles.pairingsEmpty}>Loading report…</div>}
          {report && (
            <>
              <section className={playbackStyles.playbackSection}>
                <h3 className={playbackStyles.playbackSectionHead}>Set timeline (by play order)</h3>
                {timeline.length === 0 ? (
                  <div className={pairingStyles.pairingsEmpty}>
                    No play history recorded for this event yet.
                  </div>
                ) : (
                  <ol className={playbackStyles.playbackTimeline}>
                    {timeline.map((item) =>
                      item.kind === 'slot' ? (
                        <li key={`slot-${item.slot.slot_id}`} className={playbackStyles.playbackRow}>
                          <span className={playbackStyles.playbackOrder}>{item.order}</span>
                          <span className={playbackStyles.playbackTrack}>
                            <strong>{item.slot.title ?? item.slot.track_id ?? 'Unknown track'}</strong>
                            <small>{item.slot.artist ?? 'Unknown artist'}</small>
                          </span>
                          <span className={playbackStyles.playbackPlanned}>
                            planned #{item.slot.position + 1}
                          </span>
                          <OutcomeBadge outcome={item.slot.outcome} />
                        </li>
                      ) : (
                        <li key={`unplanned-${item.order}`} className={playbackStyles.playbackRow}>
                          <span className={playbackStyles.playbackOrder}>{item.order}</span>
                          <span className={playbackStyles.playbackTrack}>
                            <strong>{item.play.title}</strong>
                            <small>{item.play.artist}</small>
                          </span>
                          <span className={playbackStyles.playbackPlanned}>not in set</span>
                          <OutcomeBadge outcome="substituted" />
                        </li>
                      ),
                    )}
                  </ol>
                )}
              </section>

              {skipped.length > 0 && (
                <section className={playbackStyles.playbackSection}>
                  <h3 className={playbackStyles.playbackSectionHead}>Planned but never played</h3>
                  <ol className={playbackStyles.playbackTimeline}>
                    {skipped.map((slot) => (
                      <li key={`skipped-${slot.slot_id}`} className={playbackStyles.playbackRow}>
                        <span className={playbackStyles.playbackOrder}>#{slot.position + 1}</span>
                        <span className={playbackStyles.playbackTrack}>
                          <strong>{slot.title ?? slot.track_id ?? 'Unknown track'}</strong>
                          <small>{slot.artist ?? 'Unknown artist'}</small>
                        </span>
                        <span className={playbackStyles.playbackPlanned} />
                        <OutcomeBadge outcome="skipped" />
                      </li>
                    ))}
                  </ol>
                </section>
              )}
            </>
          )}
        </div>

        <footer className={playbackStyles.playbackFooter}>
          <span className={playbackStyles.playbackFooterNote}>
            {applyResult ?? 'Feed back-to-back real plays into your pairing use-counts.'}
          </span>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={applying || !report}
            onClick={() => void applyPairings()}
          >
            {applying ? 'Applying…' : 'Apply to pairings'}
          </button>
        </footer>
      </div>
    </div>
  );
}
