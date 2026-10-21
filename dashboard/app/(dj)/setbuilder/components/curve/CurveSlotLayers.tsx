import type { Dispatch, SetStateAction } from 'react';
import type { SlotView } from '../types';
import type { VisibleSlotBlock } from './curveViewport';
import { BPM_TIER_COLORS, KEY_TIER_COLORS, bpmPercentDelta, camelotMixTier, fmtTime } from './curveMath';
import { SvgFixedGroup } from './FixedSvgLabels';
import styles from './curve.module.css';

const NEON = '#00f5d4';
const NEON_PURPLE = '#b78bff';
const WARNING = '#f59e0b';

type CurveView = 'normal' | 'bpm' | 'key';
interface Geometry {
  blocks: VisibleSlotBlock[];
  slots: SlotView[];
  height: number;
  viewportWidth: number;
  labelScaleX: number;
  labelScaleY: number;
  yOf: (energy: number) => number;
  linePath: string;
  totalSec: number;
  playheadX: number;
  playheadSec: number;
}
interface RenderState {
  view: CurveView;
  showBlocks: boolean;
  showDenseSeams: boolean;
  showSlotHandles: boolean;
  hoveredIdx: number | null;
  dragIdx: number | null;
  dragEnergy: number | null;
  isPlaying: boolean;
}
interface Actions {
  setDragIdx: Dispatch<SetStateAction<number | null>>;
  setDragEnergy: Dispatch<SetStateAction<number | null>>;
  onHover: (idx: number | null) => void;
  onBlockClick?: (idx: number) => void;
  onBlockDoubleClick?: (idx: number) => void;
}
interface CurveSlotLayersProps { geometry: Geometry; state: RenderState; actions: Actions }

export function CurveSlotLayers({ geometry, state, actions }: CurveSlotLayersProps) {
  const { blocks, slots, height: h, viewportWidth: effectiveViewportWidth, labelScaleX: fixedLabelScaleX,
    labelScaleY: fixedLabelScaleY, yOf, linePath, totalSec, playheadX, playheadSec } = geometry;
  const { view, showBlocks, showDenseSeams, showSlotHandles, hoveredIdx, dragIdx, dragEnergy, isPlaying } = state;
  const { setDragIdx, setDragEnergy, onHover, onBlockClick, onBlockDoubleClick } = actions;
  return (
    <>
        {/* Slot blocks */}
        {showBlocks &&
          blocks.map((b) => {
            const slot = slots[b.idx];
            const isLocked = Boolean(slot?.locked);
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
                data-locked={isLocked ? 'true' : 'false'}
                onMouseEnter={() => onHover(b.idx)}
                onMouseLeave={() => onHover(null)}
                onClick={(ev) => {
                  if ((ev.target as SVGElement).dataset?.handle) return;
                  if (onBlockClick) onBlockClick(b.idx);
                }}
                onDoubleClick={(ev) => {
                  ev.preventDefault();
                  if (onBlockDoubleClick) onBlockDoubleClick(b.idx);
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
                fillOpacity={isLocked ? (isHover ? 0.28 : 0.18) : isHover ? 0.55 : 0.13}
                stroke={isLocked ? '#fbbf24' : isHover || isDragging ? NEON : 'transparent'}
                strokeWidth={isHover || isDragging ? 1.5 : 1}
              />
              {isLocked && (
                <>
                  <rect
                    x={b.x0 + gap / 2}
                    y={0}
                    width={Math.max(1, b.width - gap)}
                    height={h}
                    fill="#fbbf24"
                    fillOpacity={isHover ? 0.08 : 0.045}
                    pointerEvents="none"
                  />
                  <SvgFixedGroup
                    x={Math.min(Math.max(b.xMid, 12), effectiveViewportWidth - 12)}
                    y={Math.max(16, h - blockH - 10)}
                    scaleX={fixedLabelScaleX}
                    scaleY={fixedLabelScaleY}
                    pointerEvents="none"
                    data-testid={`slot-lock-icon-${b.idx}`}
                  >
                    <rect
                      x={-9}
                      y={-9}
                      width={18}
                      height={18}
                      rx={3}
                      fill="var(--bg)"
                      stroke="#fbbf24"
                      strokeOpacity={0.75}
                    />
                    <path
                      d="M-4 -1v-2.2a4 4 0 0 1 8 0V-1M-5 -1h10v7H-5Z"
                      fill="none"
                      stroke="#fbbf24"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="1.3"
                    />
                  </SvgFixedGroup>
                </>
              )}
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
        {showDenseSeams &&
          view !== 'normal' &&
          blocks.slice(0, -1).map((b, i) => {
            const next = blocks[i + 1];
            const a = slots[b.idx].track;
            const z = slots[next.idx].track;
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
            const isHovered = hoveredIdx === b.idx || hoveredIdx === next.idx;
            return (
              <g
                key={`seam-${b.idx}`}
                pointerEvents="none"
                data-testid={`seam-${view}-${b.idx}`}
              >
                <rect
                  data-testid={`seam-band-${b.idx}`}
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
                  <SvgFixedGroup
                    x={Math.min(
                      Math.max(seamX, 40),
                      effectiveViewportWidth - 40,
                    )}
                    y={h - 18}
                    scaleX={fixedLabelScaleX}
                    scaleY={fixedLabelScaleY}
                    data-testid={`seam-chip-${b.idx}`}
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
                  </SvgFixedGroup>
                )}
              </g>
            );
          })}

        {/* DJ pairing seam markers */}
        {showDenseSeams &&
          blocks.slice(0, -1).map((b, i) => {
            if (!slots[b.idx].nextIsDjPairing) return null;
            const next = blocks[i + 1];
            const seamX = (b.x1 + next.x0) / 2;
            const markerY = Math.max(
              18,
              Math.min(h - 28, (yOf(b.target) + yOf(next.target)) / 2 - 18),
            );
            return (
              <g
                key={`pairing-pin-${b.idx}`}
                transform={`translate(${seamX}, ${markerY})`}
                pointerEvents="none"
                data-testid={`pairing-pin-${b.idx}`}
              >
              <line y1={10} y2={Math.max(14, h - markerY - 4)} stroke={NEON_PURPLE} strokeOpacity="0.38" strokeDasharray="2 3" />
              <circle r="10" fill="rgba(183,139,255,0.18)" stroke={NEON_PURPLE} strokeWidth="1.4" />
              <path
                d="M-3.5 2.5-.8-.2M-5.5 5.5h-.7a3.3 3.3 0 0 1 0-6.6h2.3M.9 4.2h2.3a3.3 3.3 0 1 0 0-6.6h-.7"
                fill="none"
                stroke={NEON_PURPLE}
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.3"
              />
              </g>
            );
          })}

        {/* Transport playhead */}
        {totalSec > 0 && (
          <g pointerEvents="none" data-testid="curve-playhead">
            <rect x={0} y={0} width={playheadX} height={h} fill="rgba(0,0,0,0.22)" />
            <line
              x1={playheadX}
              y1={0}
              x2={playheadX}
              y2={h}
              stroke={isPlaying ? '#00f5d4' : 'rgba(255,255,255,0.7)'}
              strokeWidth={1.5}
            />
            <SvgFixedGroup
              x={Math.min(
                Math.max(playheadX, 24),
                effectiveViewportWidth - 24,
              )}
              y={14}
              scaleX={fixedLabelScaleX}
              scaleY={fixedLabelScaleY}
              data-testid="curve-playhead-label"
            >
              <rect x={-22} y={-10} width={44} height={18} rx={3} fill="var(--bg)" stroke="#00f5d4" strokeOpacity="0.6" />
              <text
                x="0"
                y="3"
                fontSize="9"
                fill="#00f5d4"
                fontWeight="700"
                textAnchor="middle"
              >
                {fmtTime(playheadSec)}
              </text>
            </SvgFixedGroup>
          </g>
        )}

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
        {showSlotHandles &&
          blocks.map((b) => {
            if (slots[b.idx]?.locked) return null;
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
                <SvgFixedGroup
                  x={0}
                  y={-22}
                  scaleX={fixedLabelScaleX}
                  scaleY={fixedLabelScaleY}
                  pointerEvents="none"
                  data-testid="drag-chip"
                >
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
                </SvgFixedGroup>
              )}
              </g>
            );
          })}

        {/* Transport playhead lands with #393. */}
    </>
  );
}
