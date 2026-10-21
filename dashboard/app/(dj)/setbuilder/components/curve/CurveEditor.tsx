'use client';

/**
 * Slot-coupled energy curve editor (#389).
 *
 * The curve is DERIVED: a polyline through each slot's target energy at the
 * slot's midpoint. Blocks are sized by track duration (x) and intrinsic
 * energy (y). Per-slot vertical drag handles retarget; mismatch renders as
 * an amber hatch (target above energy) or dashed line (target below).
 * BPM/Key view modes render tier-colored friction bands at block seams.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type {
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
} from 'react';
import { fmtTime } from './curveMath';
import {
  curveViewportRange,
  fitPxPerSecond,
  lodForMedianSlotWidth,
  visibleBlocksFromSlots,
} from './curveViewport';
import { rawTargetSecForSlots } from './targetMath';
import type { SlotView, VibeWindowView } from '../types';
import styles from './curve.module.css';
import { SvgFixedText } from './FixedSvgLabels';
import { CurveSlotLayers } from './CurveSlotLayers';
import { VibeWindowLayer } from './VibeWindowLayer';

export type CurveViewMode = 'normal' | 'bpm' | 'key';

const WARNING = '#f59e0b';

interface ScrollbarDrag {
  startClientX: number;
  startScrollLeft: number;
  trackScrollablePx: number;
  maxScrollLeft: number;
}

export interface CurveEditorProps {
  slots: SlotView[];
  view: CurveViewMode;
  windows: VibeWindowView[];
  hoveredIdx: number | null;
  onHover: (idx: number | null) => void;
  onBlockClick?: (idx: number) => void;
  onBlockDoubleClick?: (idx: number) => void;
  playheadSec?: number;
  isPlaying?: boolean;
  scrubEnabled?: boolean;
  onScrub?: (positionSec: number) => void;
  onTargetDragEnd?: (idx: number, energy: number, anchor: { x: number; y: number }) => void;
  onWindowChange?: (id: string, patch: Partial<VibeWindowView>) => void;
  onWindowCommit?: (id: string) => void;
  onWindowDelete?: (id: string) => void;
  targetDurationSec?: number | null;
  avgTransitionOverlapSec?: number;
  pxPerSecond?: number;
  scrollLeft?: number;
  viewportWidth?: number;
  onScrollLeftChange?: (scrollLeft: number) => void;
  onViewportWidthChange?: (width: number) => void;
}

export default function CurveEditor({
  slots,
  view,
  windows,
  hoveredIdx,
  onHover,
  onBlockClick,
  onBlockDoubleClick,
  playheadSec = 0,
  isPlaying = false,
  scrubEnabled = false,
  onScrub,
  onTargetDragEnd,
  onWindowChange,
  onWindowCommit,
  onWindowDelete,
  targetDurationSec = null,
  avgTransitionOverlapSec = 0,
  pxPerSecond,
  scrollLeft,
  viewportWidth,
  onScrollLeftChange,
  onViewportWidthChange,
}: CurveEditorProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const measureFrameRef = useRef<number | null>(null);
  const scrollViewportRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [w, setW] = useState(800);
  const [h, setH] = useState(220);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dragEnergy, setDragEnergy] = useState<number | null>(null);
  const [internalScrollLeft, setInternalScrollLeft] = useState(0);
  const [scrollbarDrag, setScrollbarDrag] = useState<ScrollbarDrag | null>(null);
  const effectiveScrollLeft = scrollLeft ?? internalScrollLeft;

  const commitMeasuredSize = useCallback(
    (width: number, height: number) => {
      if (width <= 0 || height <= 0) return;
      const nextW = Math.max(1, width);
      const nextH = Math.max(1, height);
      setW((prev) => (Math.abs(prev - nextW) < 0.5 ? prev : nextW));
      setH((prev) => (Math.abs(prev - nextH) < 0.5 ? prev : nextH));
      onViewportWidthChange?.(nextW);
    },
    [onViewportWidthChange],
  );

  const measureWrap = useCallback(() => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    commitMeasuredSize(rect.width, rect.height);
  }, [commitMeasuredSize]);

  const setWrapNode = useCallback(
    (node: HTMLDivElement | null) => {
      wrapRef.current = node;
      if (measureFrameRef.current != null) {
        window.cancelAnimationFrame(measureFrameRef.current);
        measureFrameRef.current = null;
      }
      if (!node) return;
      const measureNode = () => {
        const rect = node.getBoundingClientRect();
        commitMeasuredSize(rect.width, rect.height);
      };
      measureNode();
      measureFrameRef.current = window.requestAnimationFrame(measureNode);
    },
    [commitMeasuredSize],
  );

  useLayoutEffect(() => {
    measureWrap();
  }, [measureWrap]);

  useEffect(() => {
    if (!wrapRef.current) return;
    const node = wrapRef.current;
    measureWrap();
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        commitMeasuredSize(e.contentRect.width, e.contentRect.height);
      }
    });
    ro.observe(node);
    window.addEventListener('resize', measureWrap);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', measureWrap);
      if (measureFrameRef.current != null) {
        window.cancelAnimationFrame(measureFrameRef.current);
        measureFrameRef.current = null;
      }
    };
  }, [commitMeasuredSize, measureWrap]);

  useEffect(() => {
    if (!scrollViewportRef.current) return;
    if (Math.abs(scrollViewportRef.current.scrollLeft - effectiveScrollLeft) < 1) return;
    scrollViewportRef.current.scrollLeft = effectiveScrollLeft;
  }, [effectiveScrollLeft]);

  const yOf = (e: number) => h - (e / 10) * h;
  const eOfY = (y: number) => Math.max(0, Math.min(10, (1 - y / h) * 10));

  const totalSec = slots.reduce((acc, s) => acc + s.track.durationSec, 0);
  const rawTargetSec = rawTargetSecForSlots(
    targetDurationSec,
    slots.length,
    avgTransitionOverlapSec,
  );
  const domainSec = Math.max(totalSec, rawTargetSec ?? 0, 1);
  const effectiveViewportWidth = viewportWidth ?? w;
  const effectivePxPerSecond = pxPerSecond ?? fitPxPerSecond({
    totalSec: domainSec,
    viewportWidth: effectiveViewportWidth,
  });
  const visibleRange = curveViewportRange({
    scrollLeft: effectiveScrollLeft,
    viewportWidth: effectiveViewportWidth,
    pxPerSecond: effectivePxPerSecond,
    totalSec: domainSec,
  });
  const overscanSec = Math.max(30, effectiveViewportWidth / effectivePxPerSecond);
  const targetX = rawTargetSec == null
    ? null
    : Math.round((rawTargetSec - visibleRange.startSec) * effectivePxPerSecond);
  const baseBlocks = visibleBlocksFromSlots({
    slots,
    visibleStartSec: visibleRange.startSec,
    visibleEndSec: visibleRange.endSec,
    pxPerSecond: effectivePxPerSecond,
    overscanSec,
  });
  const blocks = baseBlocks.map((b) =>
    dragIdx === b.idx && dragEnergy != null ? { ...b, target: dragEnergy } : b,
  );
  const lod = lodForMedianSlotWidth(blocks.map((b) => b.width));
  const showBlocks = lod !== 'overview';
  const showSlotHandles = lod === 'detail';
  const showDenseSeams = lod === 'detail';
  const scrollableWidth = Math.max(effectiveViewportWidth, domainSec * effectivePxPerSecond);
  const maxScrollLeft = Math.max(0, scrollableWidth - effectiveViewportWidth);
  const canScrollTimeline = maxScrollLeft > 1;
  const scrollThumbWidthPct = canScrollTimeline
    ? Math.min(100, Math.max(8, (effectiveViewportWidth / scrollableWidth) * 100))
    : 100;
  const scrollThumbLeftPct = canScrollTimeline
    ? Math.min(
        100 - scrollThumbWidthPct,
        (effectiveScrollLeft / Math.max(1, scrollableWidth)) * 100,
      )
    : 0;
  const viewBoxWidth = effectiveViewportWidth;
  const viewBoxHeight = h;
  const renderedSvgWidth = w;
  const renderedSvgHeight = h;
  const fixedLabelScaleX = viewBoxWidth / Math.max(1, renderedSvgWidth);
  const fixedLabelScaleY = viewBoxHeight / Math.max(1, renderedSvgHeight);

  const commitScrollLeft = (next: number) => {
    const clamped = Math.max(0, Math.min(maxScrollLeft, next));
    if (scrollLeft == null) setInternalScrollLeft(clamped);
    onScrollLeftChange?.(clamped);
    return clamped;
  };

  const handleScroll = (event: React.UIEvent<HTMLDivElement>) => {
    commitScrollLeft(event.currentTarget.scrollLeft);
  };

  const scrollByDelta = (delta: number) => {
    commitScrollLeft(effectiveScrollLeft + delta);
  };

  const handleScrollbarPointerDown = (ev: React.PointerEvent<HTMLDivElement>) => {
    if (!canScrollTimeline) return;
    ev.preventDefault();
    const track = ev.currentTarget;
    const trackRect = track.getBoundingClientRect();
    const thumb = track.querySelector<HTMLElement>('[data-scrollbar-thumb="1"]');
    const thumbRect = thumb?.getBoundingClientRect();
    const thumbWidth = thumbRect?.width ?? 0;
    const trackScrollablePx = Math.max(1, trackRect.width - thumbWidth);
    const clickedThumb =
      ev.target instanceof Element && Boolean(ev.target.closest('[data-scrollbar-thumb="1"]'));
    let nextScrollLeft = effectiveScrollLeft;

    if (!clickedThumb) {
      const nextThumbLeft = Math.max(
        0,
        Math.min(trackScrollablePx, ev.clientX - trackRect.left - thumbWidth / 2),
      );
      nextScrollLeft = (nextThumbLeft / trackScrollablePx) * maxScrollLeft;
      commitScrollLeft(nextScrollLeft);
    }

    setScrollbarDrag({
      startClientX: ev.clientX,
      startScrollLeft: nextScrollLeft,
      trackScrollablePx,
      maxScrollLeft,
    });
    track.setPointerCapture(ev.pointerId);
  };

  const handleScrollbarPointerMove = (ev: React.PointerEvent<HTMLDivElement>) => {
    if (!scrollbarDrag) return;
    const dx = ev.clientX - scrollbarDrag.startClientX;
    const nextScrollLeft =
      scrollbarDrag.startScrollLeft +
      (dx / scrollbarDrag.trackScrollablePx) * scrollbarDrag.maxScrollLeft;
    commitScrollLeft(nextScrollLeft);
  };

  const endScrollbarDrag = (ev: React.PointerEvent<HTMLDivElement>) => {
    if (!scrollbarDrag) return;
    setScrollbarDrag(null);
    ev.currentTarget.releasePointerCapture(ev.pointerId);
  };

  const handleScrollbarKeyDown = (ev: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!canScrollTimeline) return;
    if (ev.key === 'ArrowLeft') {
      ev.preventDefault();
      scrollByDelta(-effectiveViewportWidth / 8);
    } else if (ev.key === 'ArrowRight') {
      ev.preventDefault();
      scrollByDelta(effectiveViewportWidth / 8);
    } else if (ev.key === 'PageUp') {
      ev.preventDefault();
      scrollByDelta(-effectiveViewportWidth * 0.8);
    } else if (ev.key === 'PageDown') {
      ev.preventDefault();
      scrollByDelta(effectiveViewportWidth * 0.8);
    } else if (ev.key === 'Home') {
      ev.preventDefault();
      commitScrollLeft(0);
    } else if (ev.key === 'End') {
      ev.preventDefault();
      commitScrollLeft(maxScrollLeft);
    }
  };

  const handleWheel = (event: React.WheelEvent<SVGSVGElement>) => {
    if (!scrollViewportRef.current || maxScrollLeft <= 0) return;
    const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
    if (delta === 0) return;
    const next = commitScrollLeft(scrollViewportRef.current.scrollLeft + delta);
    scrollViewportRef.current.scrollLeft = next;
    event.preventDefault();
  };

  const clientXToDomainT = (clientX: number) => {
    if (!svgRef.current || domainSec <= 0) return null;
    const rect = svgRef.current.getBoundingClientRect();
    const viewportT = (clientX - rect.left) / Math.max(1, rect.width);
    const sec =
      visibleRange.startSec + viewportT * (effectiveViewportWidth / effectivePxPerSecond);
    return Math.max(0, Math.min(1, sec / domainSec));
  };

  // Per-slot handle drag (vertical only)
  useEffect(() => {
    if (dragIdx == null) return;
    const onMove = (ev: PointerEvent) => {
      if (!svgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      const scaleY = rect.height > 0 ? h / rect.height : 1;
      const y = (ev.clientY - rect.top) * scaleY;
      setDragEnergy(Math.round(eOfY(y) * 10) / 10);
    };
    const onUp = () => {
      if (dragEnergy != null && onTargetDragEnd) {
        const b = blocks.find((block) => block.idx === dragIdx);
        // Convert SVG-local coords to viewport coords — the popover positions
        // with `position: fixed`.
        const rect = svgRef.current?.getBoundingClientRect();
        const anchor =
          b && rect
            ? {
                x: rect.left + (b.xMid / Math.max(1, effectiveViewportWidth)) * rect.width,
                y: rect.top + (yOf(dragEnergy) / Math.max(1, h)) * rect.height,
              }
            : { x: 0, y: 0 };
        onTargetDragEnd(dragIdx, dragEnergy, anchor);
      }
      setDragIdx(null);
      setDragEnergy(null);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [dragIdx, dragEnergy, h]);

  const linePath = blocks
    .map((b, i) => `${i === 0 ? 'M' : 'L'} ${b.xMid.toFixed(2)} ${yOf(b.target).toFixed(2)}`)
    .join(' ');
  const secToX = (sec: number) =>
    (Math.max(0, Math.min(domainSec, sec)) - visibleRange.startSec) * effectivePxPerSecond;
  const playheadX = domainSec > 0 ? secToX(playheadSec) : 0;
  const scrubFromClientX = (clientX: number) => {
    if (!svgRef.current || !scrubEnabled || !onScrub || totalSec <= 0) return;
    const rect = svgRef.current.getBoundingClientRect();
    const t = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
    const sec = visibleRange.startSec + t * (effectiveViewportWidth / effectivePxPerSecond);
    onScrub(Math.min(totalSec, Math.max(0, sec)));
  };
  const handleSvgClickCapture = (ev: ReactMouseEvent<SVGSVGElement>) => {
    if (!scrubEnabled || !onScrub || totalSec <= 0) return;
    const target = ev.target;
    if (
      target instanceof Element &&
      target.closest('[data-handle="1"], [data-scrub-ignore="1"]')
    ) {
      return;
    }
    scrubFromClientX(ev.clientX);
  };

  if (slots.length === 0) {
    return (
      <div className={styles.emptyState} data-testid="curve-empty">
        Add tracks to the timeline to shape the energy curve.
      </div>
    );
  }

  return (
    <div
      className={styles.canvasWrap}
      ref={setWrapNode}
      data-testid="curve-canvas"
      data-lod={lod}
      data-px-per-second={effectivePxPerSecond.toFixed(4)}
      data-scroll-left={effectiveScrollLeft.toFixed(0)}
    >
      <span data-testid="curve-lod" className={styles.srOnly}>
        {lod}
      </span>
      <div
        ref={scrollViewportRef}
        className={styles.curveScrollViewport}
        data-testid="curve-scroll-viewport"
        data-scrollbar-affordance="true"
        aria-label="Curve timeline horizontal scroll"
        onScroll={handleScroll}
      >
        <div
          className={styles.curveScrollInner}
          style={{ width: scrollableWidth }}
          aria-hidden="true"
        />
      </div>
      <div
        className={styles.curveScrollbar}
        data-testid="curve-scrollbar"
        data-enabled={canScrollTimeline ? 'true' : 'false'}
        role="scrollbar"
        aria-label="Curve timeline scroll position"
        aria-orientation="horizontal"
        aria-valuemin={0}
        aria-valuemax={Math.round(maxScrollLeft)}
        aria-valuenow={Math.round(effectiveScrollLeft)}
        tabIndex={canScrollTimeline ? 0 : -1}
        onPointerDown={handleScrollbarPointerDown}
        onPointerMove={handleScrollbarPointerMove}
        onPointerUp={endScrollbarDrag}
        onPointerCancel={endScrollbarDrag}
        onKeyDown={handleScrollbarKeyDown}
      >
        <div
          className={styles.curveScrollbarThumb}
          data-testid="curve-scrollbar-thumb"
          data-scrollbar-thumb="1"
          style={{
            left: `${scrollThumbLeftPct}%`,
            width: `${scrollThumbWidthPct}%`,
          }}
        />
      </div>
      <svg
        ref={svgRef}
        className={styles.svg}
        viewBox={`0 0 ${effectiveViewportWidth} ${h}`}
        preserveAspectRatio="none"
        onClickCapture={handleSvgClickCapture}
        onWheel={handleWheel}
      >
        <defs>
          <pattern
            id="curveGrid"
            x="0"
            y="0"
            width={effectiveViewportWidth / 8}
            height={h / 5}
            patternUnits="userSpaceOnUse"
          >
            <path
              d={`M ${effectiveViewportWidth / 8} 0 L 0 0 0 ${h / 5}`}
              fill="none"
              stroke="rgba(255,255,255,0.04)"
              strokeWidth="1"
            />
          </pattern>
          <pattern id="mismatchPattern" patternUnits="userSpaceOnUse" width="6" height="6">
            <path
              d="M -1 1 l 2 -2 M 0 6 l 6 -6 M 5 7 l 2 -2"
              stroke={WARNING}
              strokeWidth="0.8"
              strokeOpacity="0.45"
            />
          </pattern>
        </defs>

        <rect width={effectiveViewportWidth} height={h} fill="url(#curveGrid)" />
        {scrubEnabled && (
          <rect
            width={effectiveViewportWidth}
            height={h}
            fill="transparent"
            data-testid="curve-scrub-hit"
            style={{ cursor: 'crosshair' }}
          />
        )}

        {/* Target marker + over-target region. The marker is expressed in raw
            timeline seconds needed to hit the effective target after overlaps. */}
        {rawTargetSec != null && (
          <g pointerEvents="none">
            {totalSec > rawTargetSec && targetX != null ? (
              <rect
                data-testid="curve-over-region"
                x={targetX}
                y={0}
                width={Math.max(0, (totalSec - rawTargetSec) * effectivePxPerSecond)}
                height={h}
                fill="rgba(245,158,11,0.12)"
              />
            ) : null}
            <line
              data-testid="curve-target-marker"
              x1={targetX ?? 0}
              x2={targetX ?? 0}
              y1={0}
              y2={h}
              stroke="rgba(251,191,36,0.95)"
              strokeWidth="1.5"
              strokeDasharray="5 4"
            />
            <SvgFixedText
              x={Math.min(Math.max((targetX ?? 0) + 6, 34), effectiveViewportWidth - 28)}
              y={13}
              scaleX={fixedLabelScaleX}
              scaleY={fixedLabelScaleY}
              testId="curve-target-label"
              fill="#fbbf24"
              fontSize="9"
              fontWeight="800"
              letterSpacing="0.08em"
            >
              TARGET
            </SvgFixedText>
          </g>
        )}

        {/* Peak floor reference */}
        <line
          x1="0"
          y1={yOf(8)}
          x2={effectiveViewportWidth}
          y2={yOf(8)}
          stroke="rgba(255,157,63,0.18)"
          strokeDasharray="3 4"
          strokeWidth="1"
        />

        <VibeWindowLayer
          windows={windows}
          domainSec={domainSec}
          visibleStartSec={visibleRange.startSec}
          pxPerSecond={effectivePxPerSecond}
          height={h}
          labelScaleX={fixedLabelScaleX}
          labelScaleY={fixedLabelScaleY}
          domainTimeAtClientX={clientXToDomainT}
          onWindowChange={onWindowChange}
          onWindowCommit={onWindowCommit}
          onWindowDelete={onWindowDelete}
        />

        <CurveSlotLayers
          geometry={{
            blocks, slots, height: h, viewportWidth: effectiveViewportWidth,
            labelScaleX: fixedLabelScaleX, labelScaleY: fixedLabelScaleY, yOf,
            linePath, totalSec, playheadX, playheadSec,
          }}
          state={{ view, showBlocks, showDenseSeams, showSlotHandles, hoveredIdx, dragIdx, dragEnergy, isPlaying }}
          actions={{ setDragIdx, setDragEnergy, onHover, onBlockClick, onBlockDoubleClick }}
        />
      </svg>
      <div className={styles.yaxis}>
        <div>10·peak</div>
        <div>7</div>
        <div>5</div>
        <div>2</div>
        <div>0</div>
      </div>
      <div className={styles.xaxis}>
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <div key={t}>{fmtTime(t * domainSec)}</div>
        ))}
      </div>
    </div>
  );
}
