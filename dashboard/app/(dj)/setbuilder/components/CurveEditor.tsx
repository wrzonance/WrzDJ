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

import { useEffect, useRef, useState } from 'react';
import {
  BPM_TIER_COLORS,
  KEY_TIER_COLORS,
  bpmPercentDelta,
  camelotMixTier,
  fmtTime,
  slotBlocksFromSlots,
} from './curveMath';
import type { SlotView, VibeWindowView } from './types';
import styles from './curve.module.css';

export type CurveViewMode = 'normal' | 'bpm' | 'key';

const NEON = '#00f5d4';
const NEON_PURPLE = '#b78bff';
const WARNING = '#f59e0b';

interface WindowDrag {
  id: string;
  mode: 'move' | 'left' | 'right';
  startMouseT: number;
  startT0: number;
  startT1: number;
}

export interface CurveEditorProps {
  slots: SlotView[];
  view: CurveViewMode;
  windows: VibeWindowView[];
  hoveredIdx: number | null;
  onHover: (idx: number | null) => void;
  onBlockClick?: (idx: number) => void;
  onTargetDragEnd?: (idx: number, energy: number, anchor: { x: number; y: number }) => void;
  onWindowChange?: (id: string, patch: Partial<VibeWindowView>) => void;
  onWindowCommit?: (id: string) => void;
  onWindowDelete?: (id: string) => void;
}

export default function CurveEditor({
  slots,
  view,
  windows,
  hoveredIdx,
  onHover,
  onBlockClick,
  onTargetDragEnd,
  onWindowChange,
  onWindowCommit,
  onWindowDelete,
}: CurveEditorProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [w, setW] = useState(800);
  const [h, setH] = useState(220);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dragEnergy, setDragEnergy] = useState<number | null>(null);
  const [winDrag, setWinDrag] = useState<WindowDrag | null>(null);

  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setW(Math.max(300, e.contentRect.width));
        setH(Math.max(140, e.contentRect.height));
      }
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const yOf = (e: number) => h - (e / 10) * h;
  const eOfY = (y: number) => Math.max(0, Math.min(10, (1 - y / h) * 10));

  const totalSec = slots.reduce((acc, s) => acc + s.track.durationSec, 0);
  const baseBlocks = slotBlocksFromSlots(slots, w);
  const blocks = baseBlocks.map((b) =>
    dragIdx === b.idx && dragEnergy != null ? { ...b, target: dragEnergy } : b,
  );

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
        const b = blocks[dragIdx];
        onTargetDragEnd(
          dragIdx,
          dragEnergy,
          b ? { x: b.xMid, y: yOf(dragEnergy) } : { x: 0, y: 0 },
        );
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragIdx, dragEnergy, h]);

  // Vibe-window move/resize drag
  useEffect(() => {
    if (!winDrag) return;
    const onMove = (ev: PointerEvent) => {
      if (!svgRef.current || !onWindowChange) return;
      const rect = svgRef.current.getBoundingClientRect();
      const mouseT = Math.max(0, Math.min(1, (ev.clientX - rect.left) / Math.max(1, rect.width)));
      const dt = mouseT - winDrag.startMouseT;
      if (winDrag.mode === 'move') {
        const span = winDrag.startT1 - winDrag.startT0;
        const t0 = Math.max(0, Math.min(1 - span, winDrag.startT0 + dt));
        onWindowChange(winDrag.id, { t0, t1: t0 + span });
      } else if (winDrag.mode === 'left') {
        const t0 = Math.max(0, Math.min(winDrag.startT1 - 0.02, winDrag.startT0 + dt));
        onWindowChange(winDrag.id, { t0 });
      } else {
        const t1 = Math.max(winDrag.startT0 + 0.02, Math.min(1, winDrag.startT1 + dt));
        onWindowChange(winDrag.id, { t1 });
      }
    };
    const onUp = () => {
      if (onWindowCommit) onWindowCommit(winDrag.id);
      setWinDrag(null);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [winDrag, onWindowChange, onWindowCommit]);

  const startWindowDrag =
    (id: string, mode: WindowDrag['mode'], t0: number, t1: number) =>
    (ev: React.PointerEvent) => {
      if (!svgRef.current || !onWindowChange) return;
      ev.preventDefault();
      ev.stopPropagation();
      const rect = svgRef.current.getBoundingClientRect();
      const mouseT = (ev.clientX - rect.left) / Math.max(1, rect.width);
      setWinDrag({ id, mode, startMouseT: mouseT, startT0: t0, startT1: t1 });
    };

  const linePath = blocks
    .map((b, i) => `${i === 0 ? 'M' : 'L'} ${b.xMid.toFixed(2)} ${yOf(b.target).toFixed(2)}`)
    .join(' ');

  if (slots.length === 0) {
    return (
      <div className={styles.emptyState} data-testid="curve-empty">
        Add tracks to the timeline to shape the energy curve.
      </div>
    );
  }

  return (
    <div className={styles.canvasWrap} ref={wrapRef} data-testid="curve-canvas">
      <div className={styles.yaxis}>
        <div>10·peak</div>
        <div>7</div>
        <div>5</div>
        <div>2</div>
        <div>0</div>
      </div>
      <div className={styles.xaxis}>
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <div key={t}>{fmtTime(t * totalSec)}</div>
        ))}
      </div>
      <svg
        ref={svgRef}
        className={styles.svg}
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
      >
        <defs>
          <pattern
            id="curveGrid"
            x="0"
            y="0"
            width={w / 8}
            height={h / 5}
            patternUnits="userSpaceOnUse"
          >
            <path
              d={`M ${w / 8} 0 L 0 0 0 ${h / 5}`}
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

        <rect width={w} height={h} fill="url(#curveGrid)" />

        {/* Peak floor reference */}
        <line
          x1="0"
          y1={yOf(8)}
          x2={w}
          y2={yOf(8)}
          stroke="rgba(255,157,63,0.18)"
          strokeDasharray="3 4"
          strokeWidth="1"
        />

        {/* Vibe windows */}
        {windows.map((win) => {
          const x = win.t0 * w;
          const width = Math.max(2, (win.t1 - win.t0) * w);
          const isDragging = winDrag?.id === win.id;
          const headerH = 22;
          return (
            <g key={win.id} data-testid={`vibe-window-${win.id}`}>
              <rect
                x={x}
                y={0}
                width={width}
                height={h}
                fill={isDragging ? 'rgba(183,139,255,0.18)' : 'rgba(183,139,255,0.07)'}
                stroke="rgba(183,139,255,0.4)"
                strokeWidth="1"
                pointerEvents="none"
              />
              <line x1={x} x2={x} y1={0} y2={h} stroke="rgba(183,139,255,0.6)" strokeWidth="1.5" pointerEvents="none" />
              <line x1={x + width} x2={x + width} y1={0} y2={h} stroke="rgba(183,139,255,0.6)" strokeWidth="1.5" pointerEvents="none" />
              {/* Header bar: move drag + right-click delete */}
              <rect
                x={x}
                y={0}
                width={width}
                height={headerH}
                fill={isDragging ? 'rgba(183,139,255,0.5)' : 'rgba(183,139,255,0.28)'}
                stroke="rgba(183,139,255,0.5)"
                strokeWidth="0.5"
                style={{ cursor: 'move' }}
                data-testid={`vibe-window-header-${win.id}`}
                onContextMenu={(ev) => {
                  ev.preventDefault();
                  if (onWindowDelete) onWindowDelete(win.id);
                }}
                onPointerDown={startWindowDrag(win.id, 'move', win.t0, win.t1)}
              />
              <text
                x={x + 7}
                y={headerH / 2 + 3.5}
                fontSize="9.5"
                fill="rgb(220,200,255)"
                fontWeight="700"
                letterSpacing="0.06em"
                pointerEvents="none"
              >
                {win.label.toUpperCase()}
              </text>
              {/* Resize handles */}
              <rect
                x={x - 5}
                y={0}
                width={10}
                height={h}
                fill="transparent"
                style={{ cursor: 'ew-resize' }}
                onPointerDown={startWindowDrag(win.id, 'left', win.t0, win.t1)}
              />
              <rect
                x={x + width - 5}
                y={0}
                width={10}
                height={h}
                fill="transparent"
                style={{ cursor: 'ew-resize' }}
                onPointerDown={startWindowDrag(win.id, 'right', win.t0, win.t1)}
              />
            </g>
          );
        })}

        {/* Slot blocks */}
        {blocks.map((b) => {
          const isHover = hoveredIdx === b.idx;
          const isDragging = dragIdx === b.idx;
          const gap = view === 'normal' ? 1.5 : 4;
          const blockH = (b.energy / 10) * h;
          const targetY = yOf(b.target);
          const targetAbove = b.target > b.energy + 0.5;
          const targetBelow = b.energy > b.target + 0.5;
          return (
            <g
              key={`sb-${b.idx}`}
              data-testid={`slot-block-${b.idx}`}
              onMouseEnter={() => onHover(b.idx)}
              onMouseLeave={() => onHover(null)}
              onClick={(ev) => {
                if ((ev.target as SVGElement).dataset?.handle) return;
                if (onBlockClick) onBlockClick(b.idx);
              }}
              style={{ cursor: 'pointer' }}
            >
              {/* Block (intrinsic energy) */}
              <rect
                x={b.x0 + gap / 2}
                y={h - blockH}
                width={Math.max(1, b.width - gap)}
                height={blockH}
                fill={NEON}
                fillOpacity={isHover ? 0.55 : 0.13}
                stroke={isHover || isDragging ? NEON : 'transparent'}
                strokeWidth={isHover || isDragging ? 1.5 : 1}
              />
              {/* Peak cap */}
              {b.energy >= 8 && (
                <rect
                  x={b.x0 + gap / 2}
                  y={h - blockH}
                  width={Math.max(1, b.width - gap)}
                  height={3}
                  fill="#ff9d3f"
                  fillOpacity={isHover ? 0.95 : 0.7}
                />
              )}
              {/* Mismatch: target above energy — amber hatch between block top and target */}
              {targetAbove && (
                <>
                  <rect
                    data-testid={`mismatch-above-${b.idx}`}
                    x={b.x0 + gap / 2}
                    y={targetY}
                    width={Math.max(1, b.width - gap)}
                    height={Math.max(0, h - blockH - targetY)}
                    fill={WARNING}
                    fillOpacity={isDragging ? 0.28 : 0.16}
                  />
                  <rect
                    x={b.x0 + gap / 2}
                    y={targetY}
                    width={Math.max(1, b.width - gap)}
                    height={Math.max(0, h - blockH - targetY)}
                    fill="url(#mismatchPattern)"
                  />
                </>
              )}
              {/* Mismatch: target below energy — dashed line inside the block */}
              {targetBelow && (
                <line
                  data-testid={`mismatch-below-${b.idx}`}
                  x1={b.x0 + gap / 2}
                  x2={b.x1 - gap / 2}
                  y1={targetY}
                  y2={targetY}
                  stroke={WARNING}
                  strokeWidth="1.5"
                  strokeDasharray="3 2"
                />
              )}
              {/* Invisible hit-target */}
              <rect x={b.x0} y={0} width={b.width} height={h} fill="transparent" />
            </g>
          );
        })}

        {/* Friction seams (BPM / Key views) */}
        {view !== 'normal' &&
          blocks.slice(0, -1).map((b, i) => {
            const next = blocks[i + 1];
            const a = slots[i].track;
            const z = slots[i + 1].track;
            let color: { stroke: string };
            let chipText: string;
            let isClash: boolean;
            if (view === 'bpm') {
              const info = bpmPercentDelta(a.bpm, z.bpm);
              color = BPM_TIER_COLORS[info.tier];
              chipText =
                info.pct == null
                  ? '?'
                  : `${info.pct < 0.05 ? '0' : info.pct.toFixed(1)}%${info.halfDouble ? ' · 2×' : ''}`;
              isClash = info.tier === 'clash';
            } else {
              const info = camelotMixTier(a.key, z.key);
              color = KEY_TIER_COLORS[info.tier];
              chipText = info.label;
              isClash = info.tier === 'clash';
            }
            const seamX = (b.x1 + next.x0) / 2;
            const seamW = Math.max(3, next.x0 - b.x1 - 0.5);
            // Band sized to the SHORTER neighbor block
            const meetTop = h - Math.min((b.energy / 10) * h, (next.energy / 10) * h);
            const isHovered = hoveredIdx === i || hoveredIdx === i + 1;
            return (
              <g key={`seam-${i}`} pointerEvents="none" data-testid={`seam-${view}-${i}`}>
                <rect
                  data-testid={`seam-band-${i}`}
                  data-stroke={color.stroke}
                  x={seamX - seamW / 2}
                  y={meetTop}
                  width={seamW}
                  height={h - meetTop}
                  fill={color.stroke}
                  fillOpacity={isHovered ? 0.95 : isClash ? 0.85 : 0.7}
                  rx={1}
                />
                <circle cx={seamX} cy={h - 1} r={isClash ? 3.5 : 3} fill={color.stroke} />
                {isHovered && (
                  <g
                    transform={`translate(${Math.min(Math.max(seamX, 40), w - 40)}, ${h - 18})`}
                    data-testid={`seam-chip-${i}`}
                  >
                    <rect
                      x={-Math.max(30, chipText.length * 3.4 + 7)}
                      y={-9}
                      width={Math.max(60, chipText.length * 6.8 + 14)}
                      height={16}
                      rx={3}
                      fill="var(--bg)"
                      stroke={color.stroke}
                      strokeOpacity={0.85}
                    />
                    <text
                      x={0}
                      y={2.5}
                      fontSize="9.5"
                      fill={color.stroke}
                      fontWeight="700"
                      textAnchor="middle"
                    >
                      {chipText}
                    </text>
                  </g>
                )}
              </g>
            );
          })}

        {/* Derived target curve line */}
        {linePath && (
          <path
            data-testid="curve-line"
            d={linePath}
            fill="none"
            stroke={NEON}
            strokeWidth={2}
            strokeLinejoin="miter"
            pointerEvents="none"
          />
        )}

        {/* Drag handles — one per slot at its target energy */}
        {blocks.map((b) => {
          const isHover = hoveredIdx === b.idx;
          const isDragging = dragIdx === b.idx;
          const r = isDragging ? 7 : isHover ? 6 : 5;
          const targetY = yOf(b.target);
          return (
            <g key={`h-${b.idx}`} transform={`translate(${b.xMid},${targetY})`}>
              <circle
                r={12}
                fill="transparent"
                data-handle="1"
                data-testid={`target-handle-${b.idx}`}
                onPointerDown={(ev) => {
                  ev.preventDefault();
                  ev.stopPropagation();
                  setDragIdx(b.idx);
                  setDragEnergy(b.target);
                }}
                onMouseEnter={() => onHover(b.idx)}
                style={{ cursor: dragIdx != null ? 'grabbing' : 'ns-resize' }}
              />
              <circle
                className={`${styles.point} ${isDragging ? styles.pointSelected : ''}`}
                r={r}
                pointerEvents="none"
              />
              {/* Live value chip while dragging */}
              {isDragging && (
                <g transform="translate(0,-22)" pointerEvents="none" data-testid="drag-chip">
                  <rect x={-26} y={-11} width="52" height="20" rx="3" fill="var(--bg)" stroke={NEON} />
                  <text
                    x="0"
                    y="3"
                    fontSize="11"
                    fill={NEON}
                    fontWeight="700"
                    textAnchor="middle"
                  >
                    {(dragEnergy ?? b.target).toFixed(1)}
                  </text>
                </g>
              )}
            </g>
          );
        })}

        {/* Pairing seam markers land with #392; transport playhead with #393 */}
        <g data-color-ref={NEON_PURPLE} display="none" />
      </svg>
    </div>
  );
}
