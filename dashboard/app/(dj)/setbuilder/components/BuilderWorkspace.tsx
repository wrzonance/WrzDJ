'use client';

/**
 * Builder workspace (#389) — owns the slot data + curve↔timeline shared
 * hover state and renders the Curve and Timeline grid panels. Mounted by
 * the builder page in place of the Phase 0 placeholders.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api';
import CurvePanel from './CurvePanel';
import TimelinePanel, { type ScrollRequest } from './TimelinePanel';
import TransportBar from './TransportBar';
import type { SlotView, TrackView } from './types';
import { slotViewFromApi, trackViewFromPool } from './types';
import {
  commandPayload,
  previousIndex,
  slotIndexAtPosition,
  slotStartSec,
  totalDuration,
} from './transportMath';
import sbStyles from '../setbuilder.module.css';

const SCRUB_KEY = 'wrzdj.transport.scrubEnabled';

function readScrubSetting(): boolean {
  try {
    return window.localStorage.getItem(SCRUB_KEY) !== 'false';
  } catch {
    return true;
  }
}

interface JumpSlotEvent extends Event {
  detail?: { idx?: number };
}

export default function BuilderWorkspace({
  setId,
  refreshToken = 0,
}: {
  setId: number;
  refreshToken?: number;
}) {
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

  const totalSec = useMemo(() => totalDuration(slots), [slots]);

  const loadSlots = useCallback(() => {
    return Promise.all([api.getSetSlots(setId), api.getPool(setId)])
      .then(([rows, poolState]) => {
        const poolByTrackId = new Map(
          poolState.tracks
            .filter((track) => track.track_id)
            .map((track) => [track.track_id as string, track]),
        );
        setPool(poolState.tracks.map(trackViewFromPool));
        setSlots(rows.map((slot) => slotViewFromApi(slot, poolByTrackId.get(slot.track_id ?? '') ?? null)));
      })
      .catch(() => {
        setPool([]);
        setSlots([]);
      });
  }, [setId]);

  useEffect(() => {
    let cancelled = false;
    loadSlots().catch(() => {
      if (!cancelled) setSlots([]);
    });
    return () => {
      cancelled = true;
    };
  }, [loadSlots, refreshToken]);

  useEffect(() => {
    const onPairingsChanged = () => {
      loadSlots().catch(() => {});
    };
    const onJumpSlot = (event: Event) => {
      const idx = (event as JumpSlotEvent).detail?.idx;
      if (typeof idx !== 'number') return;
      setScrollRequest((prev) => ({ idx, n: (prev?.n ?? 0) + 1 }));
    };
    window.addEventListener('wrzdj:setbuilder-pairings-changed', onPairingsChanged);
    window.addEventListener('wrzdj:setbuilder-jump-slot', onJumpSlot);
    return () => {
      window.removeEventListener('wrzdj:setbuilder-pairings-changed', onPairingsChanged);
      window.removeEventListener('wrzdj:setbuilder-jump-slot', onJumpSlot);
    };
  }, [loadSlots]);

  const handlePairingAction = async (idx: number) => {
    const from = slots[idx];
    const into = slots[idx + 1];
    if (!from || !into) return;
    if (from.nextIsDjPairing && from.nextPairingId) {
      window.dispatchEvent(
        new CustomEvent('wrzdj:open-pairings', { detail: { pairingId: from.nextPairingId } }),
      );
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
    window.dispatchEvent(new CustomEvent('wrzdj:setbuilder-pairings-changed'));
    window.dispatchEvent(
      new CustomEvent('wrzdj:open-pairings', { detail: { pairingId: saved.id } }),
    );
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

  return (
    <>
      <section className={`${sbStyles.panel} ${sbStyles.panelCurve}`} aria-label="Curve">
        <div className={sbStyles.panelHeader}>Curve</div>
        <CurvePanel
          setId={setId}
          slots={slots}
          onSlotsChange={(updater) => setSlots(updater)}
          hoveredIdx={hoveredIdx}
          onHover={setHoveredIdx}
          onBlockClick={(idx) => setScrollRequest((prev) => ({ idx, n: (prev?.n ?? 0) + 1 }))}
          onBlockDoubleClick={(idx) => jumpToSlot(idx, true)}
          playheadSec={positionSec}
          isPlaying={playing}
          scrubEnabled={scrubEnabled}
          onScrub={handleScrub}
          pool={pool}
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
        <div className={sbStyles.panelHeader}>Timeline</div>
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
        />
      </section>
    </>
  );
}
