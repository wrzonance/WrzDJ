'use client';

/**
 * Builder workspace (#389) — owns the slot data + curve↔timeline shared
 * hover state and renders the Curve and Timeline grid panels. Mounted by
 * the builder page in place of the Phase 0 placeholders.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import CurvePanel from './CurvePanel';
import TimelinePanel, { type ScrollRequest } from './TimelinePanel';
import type { SlotView } from './types';
import { slotViewFromApi } from './types';
import sbStyles from '../setbuilder.module.css';

export default function BuilderWorkspace({ setId, refreshToken = 0 }: { setId: number; refreshToken?: number }) {
  const [slots, setSlots] = useState<SlotView[]>([]);
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [scrollRequest, setScrollRequest] = useState<ScrollRequest | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSetSlots(setId)
      .then((rows) => {
        if (!cancelled) setSlots(rows.map(slotViewFromApi));
      })
      .catch(() => {
        if (!cancelled) setSlots([]);
      });
    return () => {
      cancelled = true;
    };
  }, [setId, refreshToken]);

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
        />
      </section>

      <section className={`${sbStyles.panel} ${sbStyles.panelTimeline}`} aria-label="Timeline">
        <div className={sbStyles.panelHeader}>Timeline</div>
        <TimelinePanel
          slots={slots}
          hoveredIdx={hoveredIdx}
          onHover={setHoveredIdx}
          scrollRequest={scrollRequest}
        />
      </section>
    </>
  );
}
