'use client';

/**
 * Builder workspace (#389) — owns the slot data + curve↔timeline shared
 * hover state and renders the Curve and Timeline grid panels. Mounted by
 * the builder page in place of the Phase 0 placeholders.
 */

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import CurvePanel from './CurvePanel';
import TimelinePanel, { type ScrollRequest } from './TimelinePanel';
import type { SlotView, TrackView } from './types';
import { slotViewFromApi, trackViewFromPool } from './types';
import sbStyles from '../setbuilder.module.css';

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
          pool={pool}
        />
      </section>

      <section className={`${sbStyles.panel} ${sbStyles.panelTimeline}`} aria-label="Timeline">
        <div className={sbStyles.panelHeader}>Timeline</div>
        <TimelinePanel
          slots={slots}
          hoveredIdx={hoveredIdx}
          onHover={setHoveredIdx}
          scrollRequest={scrollRequest}
          onPairingAction={handlePairingAction}
        />
      </section>
    </>
  );
}
