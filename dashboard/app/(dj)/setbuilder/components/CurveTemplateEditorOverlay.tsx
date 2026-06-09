'use client';

/**
 * Curve template editor overlay (#389) — full-canvas modal for creating and
 * editing reusable energy-curve templates. Draggable SVG canvas + point list.
 * Built-in templates open as a read-only starting point (Save-as-copy only).
 */

import { useEffect, useRef, useState } from 'react';
import type { CurvePoint } from '@/lib/api-types';
import styles from './curve.module.css';

const NEON = '#00f5d4';

const BLANK_POINTS: CurvePoint[] = [
  { t: 0, e: 3, label: 'Start', slow_start: false, slow_end: false },
  { t: 0.5, e: 7, label: 'Mid', slow_start: false, slow_end: false },
  { t: 1, e: 5, label: 'End', slow_start: false, slow_end: false },
];

export interface TemplateDraft {
  id?: number;
  name: string;
  points: CurvePoint[];
}

export interface CurveTemplateEditorOverlayProps {
  open: boolean;
  mode: 'create' | 'edit';
  initial: TemplateDraft | null;
  isBuiltIn: boolean;
  onSaveNew: (draft: TemplateDraft) => void;
  onSaveCurrent: (draft: TemplateDraft) => void;
  onDelete: (templateId: number) => void;
  onClose: () => void;
}

export default function CurveTemplateEditorOverlay({
  open,
  mode,
  initial,
  isBuiltIn,
  onSaveNew,
  onSaveCurrent,
  onDelete,
  onClose,
}: CurveTemplateEditorOverlayProps) {
  const [name, setName] = useState('');
  const [points, setPoints] = useState<CurvePoint[]>([]);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [w, setW] = useState(820);
  const [h, setH] = useState(320);

  // Reset on open
  useEffect(() => {
    if (!open) return;
    if (initial) {
      setName(isBuiltIn ? `${initial.name} (copy)` : initial.name);
      setPoints(initial.points.map((p) => ({ ...p })));
    } else {
      setName('Untitled curve');
      setPoints(BLANK_POINTS.map((p) => ({ ...p })));
    }
    setSelectedIdx(null);
  }, [open, initial, isBuiltIn]);

  useEffect(() => {
    if (!open || !wrapRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setW(Math.max(400, e.contentRect.width));
        setH(Math.max(200, e.contentRect.height));
      }
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [open]);

  // Keyboard: escape closes, delete removes selected interior point
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (
        (e.key === 'Delete' || e.key === 'Backspace') &&
        selectedIdx != null &&
        (e.target as HTMLElement).tagName?.toLowerCase() !== 'input'
      ) {
        e.preventDefault();
        removePoint(selectedIdx);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, selectedIdx, points]);

  // Point drag
  useEffect(() => {
    if (dragIdx == null) return;
    const onMove = (ev: PointerEvent) => {
      if (!svgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      const scaleX = rect.width > 0 ? w / rect.width : 1;
      const scaleY = rect.height > 0 ? h / rect.height : 1;
      const x = (ev.clientX - rect.left) * scaleX;
      const y = (ev.clientY - rect.top) * scaleY;
      setPoints((prev) =>
        prev.map((p, i) => {
          if (i !== dragIdx) return p;
          const newT =
            i === 0
              ? 0
              : i === prev.length - 1
                ? 1
                : Math.max(prev[i - 1].t + 0.005, Math.min(prev[i + 1].t - 0.005, x / w));
          const newE = Math.max(0, Math.min(10, (1 - y / h) * 10));
          return { ...p, t: Math.round(newT * 1000) / 1000, e: Math.round(newE * 10) / 10 };
        }),
      );
    };
    const onUp = () => setDragIdx(null);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [dragIdx, w, h]);

  if (!open) return null;

  const xOf = (t: number) => t * w;
  const yOf = (e: number) => h - (e / 10) * h;

  const addPointAt = (ev: React.MouseEvent) => {
    if ((ev.target as SVGElement).dataset?.handle) return;
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const scaleX = rect.width > 0 ? w / rect.width : 1;
    const scaleY = rect.height > 0 ? h / rect.height : 1;
    const t = Math.max(0, Math.min(1, ((ev.clientX - rect.left) * scaleX) / w));
    const e = Math.max(0, Math.min(10, (1 - ((ev.clientY - rect.top) * scaleY) / h) * 10));
    setPoints((prev) => {
      if (prev.length >= 32) return prev;
      const insertIdx = prev.findIndex((p) => p.t > t);
      const idx = insertIdx === -1 ? prev.length - 1 : insertIdx;
      if (idx === 0 || idx >= prev.length) return prev;
      const next = [...prev];
      next.splice(idx, 0, {
        t: Math.round(t * 1000) / 1000,
        e: Math.round(e * 10) / 10,
        label: '',
        slow_start: false,
        slow_end: false,
      });
      setSelectedIdx(idx);
      return next;
    });
  };

  const removePoint = (i: number) => {
    if (i === 0 || i === points.length - 1) return; // endpoints locked
    setPoints((prev) => prev.filter((_, j) => j !== i));
    setSelectedIdx(null);
  };

  const updatePoint = (i: number, patch: Partial<CurvePoint>) => {
    setPoints((prev) => prev.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  };

  const linePath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xOf(p.t).toFixed(2)} ${yOf(p.e).toFixed(2)}`)
    .join(' ');
  const fillPath = `${linePath} L ${w} ${h} L 0 ${h} Z`;

  const nameOk = name.trim().length > 0;
  const canSaveCurrent = !isBuiltIn && initial?.id != null && nameOk;

  return (
    <div className={styles.overlayWrap} role="dialog" aria-label="Curve template editor">
      <div className={styles.overlayBackdrop} onClick={onClose} data-testid="overlay-backdrop" />
      <div className={styles.overlayShell}>
        <div className={styles.overlayHeader}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className={styles.overlayEyebrow}>
              {mode === 'create'
                ? 'Create curve template'
                : isBuiltIn
                  ? `Editing built-in · "${initial?.name}"`
                  : 'Edit template'}
            </div>
            <input
              className={styles.overlayNameInput}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Template name…"
              aria-label="Template name"
            />
          </div>
          {isBuiltIn && (
            <div
              className={styles.readonlyBadge}
              title="Built-in templates can't be overwritten — use Save as new copy"
            >
              read-only original
            </div>
          )}
          <button className="btn btn-sm" onClick={onClose} title="Close (esc)">
            ✕
          </button>
        </div>

        <div className={styles.overlayBody}>
          <div className={styles.overlayCanvasCol}>
            <div className={styles.overlayHelp}>
              <kbd>double-click</kbd> empty area to add · <kbd>drag</kbd> any point ·{' '}
              <kbd>delete</kbd> selected (endpoints locked)
            </div>
            <div className={styles.overlayCanvas} ref={wrapRef}>
              <div className={styles.yaxis}>
                <div>10·peak</div>
                <div>7</div>
                <div>5</div>
                <div>2</div>
                <div>0</div>
              </div>
              <div className={styles.xaxis}>
                <div>0%</div>
                <div>25%</div>
                <div>50%</div>
                <div>75%</div>
                <div>100%</div>
              </div>
              <svg
                ref={svgRef}
                className={styles.svg}
                viewBox={`0 0 ${w} ${h}`}
                preserveAspectRatio="none"
                onDoubleClick={addPointAt}
                data-testid="template-canvas"
              >
                <defs>
                  <linearGradient id="cteFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={NEON} stopOpacity="0.28" />
                    <stop offset="60%" stopColor={NEON} stopOpacity="0.06" />
                    <stop offset="100%" stopColor={NEON} stopOpacity="0" />
                  </linearGradient>
                </defs>
                <line
                  x1="0"
                  y1={yOf(8)}
                  x2={w}
                  y2={yOf(8)}
                  stroke="rgba(255,157,63,0.18)"
                  strokeDasharray="3 4"
                  strokeWidth="1"
                />
                <path d={fillPath} fill="url(#cteFill)" />
                <path d={linePath} fill="none" stroke={NEON} strokeWidth="2.5" strokeLinejoin="round" />
                {points.map((p, i) => {
                  const isSelected = selectedIdx === i;
                  const isEndpoint = i === 0 || i === points.length - 1;
                  return (
                    <g
                      key={i}
                      transform={`translate(${xOf(p.t)},${yOf(p.e)})`}
                      style={{ cursor: 'grab' }}
                    >
                      <circle
                        r={14}
                        fill="transparent"
                        data-handle="1"
                        data-testid={`template-point-${i}`}
                        onPointerDown={(ev) => {
                          ev.preventDefault();
                          ev.stopPropagation();
                          setDragIdx(i);
                          setSelectedIdx(i);
                        }}
                        onClick={() => setSelectedIdx(i)}
                        onDoubleClick={(e) => e.stopPropagation()}
                      />
                      <circle
                        r={isSelected ? 8 : 6}
                        fill={isSelected ? NEON : 'var(--bg)'}
                        stroke={isSelected ? NEON : isEndpoint ? 'var(--color-warning)' : NEON}
                        strokeWidth={isSelected ? 2.5 : 2}
                        pointerEvents="none"
                      />
                    </g>
                  );
                })}
              </svg>
            </div>
          </div>

          {/* Point list sidebar */}
          <div className={styles.overlaySide}>
            <div className={styles.overlaySideHeader}>
              <span>Points</span>
              <span data-testid="point-count">{points.length}</span>
            </div>
            <div className={styles.pointsList}>
              {points.map((p, i) => {
                const isEndpoint = i === 0 || i === points.length - 1;
                return (
                  <div
                    key={i}
                    className={`${styles.pointRow} ${selectedIdx === i ? styles.pointRowSelected : ''}`}
                    onClick={() => setSelectedIdx(i)}
                    data-testid={`point-row-${i}`}
                  >
                    <div className={styles.pointNum}>{String(i + 1).padStart(2, '0')}</div>
                    <input
                      className={styles.pointLabelInput}
                      value={p.label ?? ''}
                      onChange={(e) => updatePoint(i, { label: e.target.value })}
                      placeholder={isEndpoint ? (i === 0 ? 'start' : 'end') : 'label'}
                      aria-label={`Point ${i + 1} label`}
                    />
                    <div className={styles.pointT}>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        value={Math.round(p.t * 100)}
                        disabled={isEndpoint}
                        onChange={(e) => {
                          const v = parseInt(e.target.value, 10) || 0;
                          const raw = Math.max(0, Math.min(1, v / 100));
                          // Clamp to neighbors — manual edits must respect the
                          // same monotonic ordering the drag logic enforces.
                          const minT = i > 0 ? points[i - 1].t + 0.005 : 0;
                          const maxT = i < points.length - 1 ? points[i + 1].t - 0.005 : 1;
                          updatePoint(i, { t: Math.max(minT, Math.min(maxT, raw)) });
                        }}
                        aria-label={`Point ${i + 1} position`}
                      />
                      <span>%</span>
                    </div>
                    <div className={styles.pointE}>
                      <input
                        type="range"
                        min={0}
                        max={10}
                        step={0.1}
                        value={p.e}
                        onChange={(e) => updatePoint(i, { e: parseFloat(e.target.value) })}
                        aria-label={`Point ${i + 1} energy`}
                      />
                      <span>{p.e.toFixed(1)}</span>
                    </div>
                    {!isEndpoint && (
                      <button
                        className={styles.pointDel}
                        onClick={(e) => {
                          e.stopPropagation();
                          removePoint(i);
                        }}
                        title="Delete point"
                        data-testid={`point-del-${i}`}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            <div className={styles.overlayFootnote}>
              Endpoints are locked at 0% and 100%. Built-in templates can only be saved as a new
              copy.
            </div>
          </div>
        </div>

        <div className={styles.overlayFooter}>
          {!isBuiltIn && initial?.id != null && (
            <button
              className="btn btn-sm"
              style={{ color: 'var(--color-danger)' }}
              data-testid="template-delete"
              onClick={() => {
                if (window.confirm(`Delete template "${initial.name}"?`)) {
                  onDelete(initial.id as number);
                  onClose();
                }
              }}
            >
              Delete
            </button>
          )}
          <div style={{ flex: 1 }} />
          <button className="btn btn-sm" onClick={onClose}>
            Cancel
          </button>
          {canSaveCurrent && (
            <button
              className="btn btn-sm btn-primary"
              disabled={!nameOk}
              data-testid="template-save"
              onClick={() => {
                onSaveCurrent({ id: initial?.id, name: name.trim(), points });
                onClose();
              }}
            >
              Save changes
            </button>
          )}
          <button
            className="btn btn-sm btn-primary"
            disabled={!nameOk}
            data-testid="template-save-as"
            onClick={() => {
              onSaveNew({ name: name.trim(), points });
              onClose();
            }}
          >
            {isBuiltIn ? 'Save as new copy' : 'Save as new'}
          </button>
        </div>
      </div>
    </div>
  );
}
