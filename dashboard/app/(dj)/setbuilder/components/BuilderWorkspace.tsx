'use client';

/**
 * Builder workspace (#389) — owns the slot data + curve↔timeline shared
 * hover state and renders the Curve and Timeline grid panels. Mounted by
 * the builder page in place of the Phase 0 placeholders.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { SetDocumentSnapshot } from '@/lib/api/types';
import CurvePanel from './curve/CurvePanel';
import TimelinePanel, { type ScrollRequest } from './timeline/TimelinePanel';
import TransportBar from './TransportBar';
import type { ConfirmAction } from './ConfirmActionDialog';
import {
  formatTimecode,
  projectTarget,
  type TargetProjection,
  type TargetSettings,
} from './curve/targetMath';
import type { SlotView, TrackView } from './types';
import { slotViewFromApi, trackViewFromPool } from './types';
import type { BuilderCommit } from './useSetDocumentHistory';
import {
  commandPayload,
  previousIndex,
  slotIndexAtPosition,
  slotStartSec,
  totalDuration,
} from './timeline/transportMath';
import { buildMovedIds, buildReorderedIds } from './reorderMath';
import { insertPoolTrackIntoDocument, lockSlotsInDocument } from './documentMath';
import { getUnlockedSlotIdsBeforePlayhead } from './playheadLock';
import sbStyles from '../setbuilder.module.css';

const SCRUB_KEY = 'wrzdj.transport.scrubEnabled';

function readScrubSetting(): boolean {
  try {
    return window.localStorage.getItem(SCRUB_KEY) !== 'false';
  } catch {
    return true;
  }
}

interface BuilderWorkspaceProps {
  setId: number;
  jumpSlotRequest?: { idx: number; requestId: number } | null;
  onOpenPairings?: (pairingId?: number | null) => void;
  onPairingsChanged?: () => void;
  refreshToken?: number;
  snapshot?: SetDocumentSnapshot | null;
  snapshotVersion?: number;
  commit?: BuilderCommit;
  suggestReplacements?: boolean;
  onSuggestReplacementsChange?: (checked: boolean) => void;
  confirmRecompute?: boolean;
  requestConfirmation?: (action: ConfirmAction) => Promise<boolean>;
  targetSettings?: TargetSettings;
  onProjectionChange?: (projection: TargetProjection) => void;
}

const DEFAULT_TARGET_SETTINGS: TargetSettings = {
  targetDurationSec: null,
  avgTransitionOverlapSec: 8,
};

function TimelineSummary({
  projection,
  overlapSec,
}: {
  projection: TargetProjection;
  overlapSec: number;
}) {
  const avgTrackSec = projection.slotCount > 0 ? projection.rawTotalSec / projection.slotCount : 0;
  const overlapPct = avgTrackSec > 0 ? (overlapSec / avgTrackSec) * 100 : 0;
  return (
    <div className={sbStyles.timelineSummary} data-testid="timeline-summary">
      <span>
        <strong>{projection.slotCount}</strong> tracks
      </span>
      <span>
        <strong>{formatTimecode(projection.rawTotalSec)}</strong> raw
      </span>
      {projection.slotCount > 1 && overlapSec > 0 ? (
        <span className={sbStyles.timelineLiveWrap}>
          <span className={sbStyles.timelineLive} tabIndex={0}>
            <strong>{formatTimecode(projection.effectiveSec)}</strong> live, est.
          </span>
          <span className={sbStyles.timelineTooltip} role="tooltip">
            <strong>Estimated live runtime</strong>
            <span>Actual runtime depends on how you blend on the night.</span>
            <span className={sbStyles.timelineTooltipGrid}>
              <span>Raw total</span>
              <b>{formatTimecode(projection.rawTotalSec)}</b>
              <span>Transitions</span>
              <b>{projection.transitionCount} x {overlapSec}s overlap</b>
              <span>~% of avg track</span>
              <b>{overlapPct.toFixed(1)}%</b>
              <span>Live (est.)</span>
              <b>{formatTimecode(projection.effectiveSec)}</b>
            </span>
          </span>
        </span>
      ) : null}
    </div>
  );
}

export default function BuilderWorkspace({
  setId,
  jumpSlotRequest = null,
  onOpenPairings,
  onPairingsChanged,
  refreshToken = 0,
  snapshot,
  snapshotVersion = 0,
  commit,
  suggestReplacements,
  onSuggestReplacementsChange,
  confirmRecompute = true,
  requestConfirmation,
  targetSettings = DEFAULT_TARGET_SETTINGS,
  onProjectionChange,
}: BuilderWorkspaceProps) {
  const [slots, setSlots] = useState<SlotView[]>([]);
  const [pool, setPool] = useState<TrackView[]>([]);
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [scrollRequest, setScrollRequest] = useState<ScrollRequest | null>(null);
  const [positionSec, setPositionSec] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [scrubEnabled, setScrubEnabled] = useState(true);
  const [bridgeStatus, setBridgeStatus] = useState({
    connected: false,
    active_source: null as string | null,
    device_name: null as string | null,
  });
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const loadSequence = useRef(0);

  const totalSec = useMemo(() => totalDuration(slots), [slots]);
  const projection = useMemo(
    () => projectTarget(slots, targetSettings),
    [slots, targetSettings],
  );

  const loadSlots = useCallback(async (): Promise<boolean> => {
    const sequence = ++loadSequence.current;
    setWorkspaceLoading(true);
    setWorkspaceError(null);
    try {
      const [rows, poolState] = await Promise.all([api.getSetSlots(setId), api.getPool(setId)]);
      if (sequence !== loadSequence.current) return false;
      const poolByTrackId = new Map<string, (typeof poolState.tracks)[number]>();
      for (const track of poolState.tracks) {
        if (track.track_id) poolByTrackId.set(track.track_id, track);
        poolByTrackId.set(`pool:${track.id}`, track);
      }
      setPool(poolState.tracks.map(trackViewFromPool));
      setSlots(rows.map((slot) => slotViewFromApi(slot, poolByTrackId.get(slot.track_id ?? '') ?? null)));
      setWorkspaceLoading(false);
      return true;
    } catch {
      if (sequence === loadSequence.current) {
        setWorkspaceError('Could not load set. Your current workspace is still available.');
        setWorkspaceLoading(false);
      }
      return false;
    }
  }, [setId]);

  useEffect(() => {
    loadSlots();
    return () => {
      loadSequence.current += 1;
    };
  }, [loadSlots, refreshToken, snapshotVersion]);

  useEffect(() => {
    if (!jumpSlotRequest) return;
    setScrollRequest((previous) => ({ idx: jumpSlotRequest.idx, n: (previous?.n ?? 0) + 1 }));
  }, [jumpSlotRequest]);

  const handlePairingAction = async (idx: number) => {
    const from = slots[idx];
    const into = slots[idx + 1];
    if (!from || !into) return;
    if (from.nextIsDjPairing && from.nextPairingId) {
      onOpenPairings?.(from.nextPairingId);
      return;
    }
    const saved = await api.savePairing(setId, {
      from_track_id: from.track.id,
      into_track_id: into.track.id,
      cue_in_sec: null,
      note: null,
      tags: [],
      increment_use_count: true,
    });
    onPairingsChanged?.();
    onOpenPairings?.(saved.id);
  };

  useEffect(() => {
    setScrubEnabled(readScrubSetting());
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadStatus = () => {
      api
        .getTransportStatus(setId)
        .then((status) => {
          if (!cancelled) {
            setBridgeStatus({
              connected: status.connected,
              active_source: status.active_source,
              device_name: status.device_name,
            });
          }
        })
        .catch(() => {
          if (!cancelled) {
            setBridgeStatus({ connected: false, active_source: null, device_name: null });
          }
        });
    };
    loadStatus();
    const timer = window.setInterval(loadStatus, 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [setId]);

  const sendCommand = useCallback(
    (idx: number, action: 'load' | 'play' | 'pause' | 'seek', absolutePosition: number) => {
      const payload = commandPayload(slots, idx, action, absolutePosition);
      if (!payload) return;
      api
        .sendTransportCommand(setId, payload)
        .then((resp) => {
          setBridgeStatus((prev) => ({ ...prev, active_source: resp.active_source }));
        })
        .catch(() => {});
    },
    [setId, slots],
  );

  useEffect(() => {
    if (!playing || totalSec <= 0) return;
    const timer = window.setInterval(() => {
      setPositionSec((prev) => {
        const next = Math.min(totalSec, prev + 1);
        if (next >= totalSec) {
          const finalIdx = slotIndexAtPosition(slots, Math.max(0, totalSec - 0.001));
          if (finalIdx >= 0) {
            sendCommand(finalIdx, 'pause', totalSec);
          }
          setPlaying(false);
          return totalSec;
        }
        const nextIdx = slotIndexAtPosition(slots, next);
        setCurrentIdx((oldIdx) => {
          if (nextIdx !== oldIdx && nextIdx >= 0) {
            sendCommand(nextIdx, 'play', next);
            return nextIdx;
          }
          return oldIdx;
        });
        return next;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [playing, sendCommand, slots, totalSec]);

  const jumpToSlot = (idx: number, shouldPlay: boolean) => {
    const next = Math.max(0, Math.min(idx, slots.length - 1));
    const pos = slotStartSec(slots, next);
    setPositionSec(pos);
    setCurrentIdx(next);
    setPlaying(shouldPlay);
    sendCommand(next, shouldPlay ? 'play' : 'load', pos);
  };

  const handlePrev = () => {
    if (slots.length === 0) return;
    const nextIdx = previousIndex(slots, currentIdx, positionSec);
    jumpToSlot(nextIdx, playing);
  };

  const handleNext = () => {
    if (slots.length === 0) return;
    const nextIdx = Math.min(slots.length - 1, currentIdx + 1);
    jumpToSlot(nextIdx, playing);
  };

  const handleToggle = () => {
    if (slots.length === 0) return;
    const idx = slotIndexAtPosition(slots, positionSec);
    setCurrentIdx(idx);
    setPlaying((wasPlaying) => {
      sendCommand(idx, wasPlaying ? 'pause' : 'play', positionSec);
      return !wasPlaying;
    });
  };

  const handleScrub = (nextPosition: number) => {
    if (!scrubEnabled || slots.length === 0) return;
    const bounded = Math.max(0, Math.min(totalSec, nextPosition));
    const idx = slotIndexAtPosition(slots, bounded);
    setPositionSec(bounded);
    setCurrentIdx(idx);
    sendCommand(idx, 'seek', bounded);
  };

  const handlePoolTrackDrop = useCallback(
    async (poolTrackId: number, insertIdx: number) => {
      if (slots.some((slot, idx) => slot.locked && idx >= insertIdx)) return;
      const save = async () => {
        const current = await api.getSetDocument(setId);
        return api.putSetDocument(
          setId,
          insertPoolTrackIntoDocument(current, poolTrackId, insertIdx),
        );
      };
      try {
        const run = commit ? commit('Insert pool track', save) : save();
        await run;
        const loaded = await loadSlots();
        if (!loaded) {
          setWorkspaceError('Track was saved, but the timeline could not refresh. Reload before trying again.');
        }
      } catch {
        const reconciled = await loadSlots();
        setWorkspaceError(
          reconciled
            ? 'Could not confirm the insert. The timeline was reloaded from saved data; check it before trying again.'
            : 'Could not confirm the insert or reload the timeline. Reload before trying again.',
        );
      }
    },
    [commit, loadSlots, setId, slots],
  );

  const handleSlotReorder = useCallback(
    async (slotId: number, insertIdx: number) => {
      const orderedIds = buildReorderedIds(slots, slotId, insertIdx);
      if (!orderedIds) return;
      const save = async () => api.reorderSlots(setId, orderedIds);
      try {
        const run = commit ? commit('Reorder slot', save) : save();
        await run;
        await loadSlots();
      } catch {
        await loadSlots();
      }
    },
    [commit, loadSlots, setId, slots],
  );

  const handleMoveSlot = useCallback(
    async (slotId: number, direction: 'up' | 'down') => {
      const orderedIds = buildMovedIds(slots, slotId, direction);
      if (!orderedIds) return;
      const save = async () => api.reorderSlots(setId, orderedIds);
      try {
        const run = commit ? commit('Move slot', save) : save();
        await run;
        await loadSlots();
      } catch {
        await loadSlots();
      }
    },
    [commit, loadSlots, setId, slots],
  );

  const handleSlotLockChange = useCallback(
    async (slotIds: number[], locked: boolean, label?: string) => {
      if (slotIds.length === 0) return;
      const slotIdSet = new Set(slotIds);
      setSlots((prev) =>
        prev.map((slot) => (slotIdSet.has(slot.id) ? { ...slot, locked } : slot)),
      );
      const actionLabel =
        label ??
        `${locked ? 'Lock' : 'Unlock'} ${slotIds.length === 1 ? 'slot' : `${slotIds.length} slots`}`;
      const save = async () => {
        const current = await api.getSetDocument(setId);
        return api.putSetDocument(setId, lockSlotsInDocument(current, slotIds, locked));
      };
      try {
        const run = commit ? commit(actionLabel, save) : save();
        await run;
        await loadSlots();
      } catch {
        await loadSlots();
      }
    },
    [commit, loadSlots, setId],
  );

  const handleLockBeforePlayhead = useCallback(async () => {
    const ids = getUnlockedSlotIdsBeforePlayhead(slots, positionSec);
    await handleSlotLockChange(ids, true, 'Lock slots before playhead');
  }, [handleSlotLockChange, positionSec, slots]);

  useEffect(() => {
    onProjectionChange?.(projection);
  }, [projection, onProjectionChange]);

  return (
    <>
      {workspaceError && (
        <div role="alert" className={sbStyles.panel}>
          <span>{workspaceError}</span>{' '}
          <button
            type="button"
            className="btn btn-sm"
            data-testid="workspace-retry"
            onClick={() => void loadSlots()}
            disabled={workspaceLoading}
          >
            {workspaceLoading ? 'Retrying…' : 'Retry'}
          </button>
        </div>
      )}
      <section className={`${sbStyles.panel} ${sbStyles.panelCurve}`} aria-label="Curve">
        <div className={sbStyles.panelHeader}>Curve</div>
        <CurvePanel
          setId={setId}
          slots={slots}
          onSlotsChange={(updater) => setSlots(updater)}
          snapshot={snapshot}
          snapshotVersion={snapshotVersion}
          commit={commit}
          hoveredIdx={hoveredIdx}
          onHover={setHoveredIdx}
          onBlockClick={(idx) => setScrollRequest((prev) => ({ idx, n: (prev?.n ?? 0) + 1 }))}
          onBlockDoubleClick={(idx) => jumpToSlot(idx, true)}
          playheadSec={positionSec}
          isPlaying={playing}
          scrubEnabled={scrubEnabled}
          onScrub={handleScrub}
          pool={pool}
          suggestReplacementsSetting={suggestReplacements}
          onSuggestReplacementsChange={onSuggestReplacementsChange}
          confirmRecompute={confirmRecompute}
          requestConfirmation={requestConfirmation}
          targetDurationSec={targetSettings.targetDurationSec}
          avgTransitionOverlapSec={targetSettings.avgTransitionOverlapSec}
        />
      </section>

      <section className={`${sbStyles.panel} ${sbStyles.panelTransport}`} aria-label="Transport">
        <TransportBar
          slots={slots}
          currentIdx={currentIdx}
          positionSec={positionSec}
          playing={playing}
          status={bridgeStatus}
          onPrev={handlePrev}
          onToggle={handleToggle}
          onNext={handleNext}
        />
      </section>

      <section className={`${sbStyles.panel} ${sbStyles.panelTimeline}`} aria-label="Timeline">
        <div className={sbStyles.panelHeaderRow}>
          <div className={sbStyles.panelHeader}>Timeline</div>
          <TimelineSummary
            projection={projection}
            overlapSec={targetSettings.avgTransitionOverlapSec}
          />
        </div>
        <TimelinePanel
          slots={slots}
          hoveredIdx={hoveredIdx}
          currentIdx={currentIdx}
          positionSec={positionSec}
          playing={playing}
          onHover={setHoveredIdx}
          onRowDoubleClick={(idx) => jumpToSlot(idx, true)}
          scrollRequest={scrollRequest}
          onPairingAction={handlePairingAction}
          onPoolTrackDrop={handlePoolTrackDrop}
          onSlotReorder={handleSlotReorder}
          onMoveSlot={handleMoveSlot}
          onSlotLockChange={handleSlotLockChange}
          onLockBeforePlayhead={handleLockBeforePlayhead}
        />
      </section>
    </>
  );
}
