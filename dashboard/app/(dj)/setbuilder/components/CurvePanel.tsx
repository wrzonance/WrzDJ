'use client';

/**
 * Curve panel container (#389) — wires the SVG editor, toolbar, template
 * overlay, vibe windows, and replacement popover to the setbuilder API.
 *
 * Targets persist per slot (PATCH on drag-release); templates apply
 * server-side (slot midpoints computed from track durations); vibe windows
 * sync via replace-all PUT. Pool candidates arrive via the `pool` prop
 * (empty until #388 lands).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { CurveTemplatesResponse, SetDocumentSnapshot } from '@/lib/api-types';
import CurveEditor, { type CurveViewMode } from './CurveEditor';
import CurveToolbar from './CurveToolbar';
import CurveTemplateEditorOverlay, { type TemplateDraft } from './CurveTemplateEditorOverlay';
import type { ConfirmAction } from './ConfirmActionDialog';
import ReplacePopover, { type ReplacePrompt } from './ReplacePopover';
import {
  REPLACE_PROMPT_THRESHOLD,
  rankReplacementCandidates,
  slotMidpoints,
  type VibePreset,
} from './curveMath';
import { fitPxPerSecond, zoomPxPerSecond } from './curveViewport';
import type { SlotView, TrackView, VibeWindowView } from './types';
import type { BuilderCommit } from './useSetDocumentHistory';

const SUGGEST_KEY = 'wrzdj.curve.suggestReplacements';

function readSuggestSetting(): boolean | null {
  try {
    const stored = window.localStorage.getItem(SUGGEST_KEY);
    return stored == null ? null : stored !== 'false';
  } catch {
    // localStorage unavailable (SSR, privacy mode)
    return null;
  }
}

function writeSuggestSetting(on: boolean): void {
  try {
    window.localStorage.setItem(SUGGEST_KEY, String(on));
  } catch {
    // best-effort persistence only
  }
}

interface OverlayState {
  open: boolean;
  mode: 'create' | 'edit';
  initial: TemplateDraft | null;
  isBuiltIn: boolean;
}

const OVERLAY_CLOSED: OverlayState = { open: false, mode: 'create', initial: null, isBuiltIn: false };

function windowsFromSnapshot(
  snapshot: SetDocumentSnapshot | null | undefined,
  totalSec: number,
): VibeWindowView[] | null {
  if (!snapshot || totalSec <= 0) return null;
  const rows = [...snapshot.curve_points].sort((a, b) => a.id - b.id);
  const windows: VibeWindowView[] = [];
  let open: (typeof rows)[number] | null = null;
  for (const row of rows) {
    if (row.is_slow_window_start) open = row;
    else if (row.is_slow_window_end && open) {
      windows.push({
        id: `sw-${open.id}-${row.id}`,
        t0: Math.min(1, open.position_sec / totalSec),
        t1: Math.min(1, row.position_sec / totalSec),
        label: open.label ?? 'Vibe window',
      });
      open = null;
    }
  }
  return windows;
}

export interface CurvePanelProps {
  setId: number;
  slots: SlotView[];
  onSlotsChange: (updater: (prev: SlotView[]) => SlotView[]) => void;
  hoveredIdx: number | null;
  onHover: (idx: number | null) => void;
  onBlockClick: (idx: number) => void;
  onBlockDoubleClick?: (idx: number) => void;
  playheadSec?: number;
  isPlaying?: boolean;
  scrubEnabled?: boolean;
  onScrub?: (positionSec: number) => void;
  snapshot?: SetDocumentSnapshot | null;
  snapshotVersion?: number;
  commit?: BuilderCommit;
  /** Candidate pool for the replacement popover (#388 feeds this). */
  pool?: TrackView[];
  suggestReplacementsSetting?: boolean;
  onSuggestReplacementsChange?: (on: boolean) => void;
  confirmRecompute?: boolean;
  requestConfirmation?: (action: ConfirmAction) => Promise<boolean>;
  targetDurationSec?: number | null;
  avgTransitionOverlapSec?: number;
}

export default function CurvePanel({
  setId,
  slots,
  onSlotsChange,
  hoveredIdx,
  onHover,
  onBlockClick,
  onBlockDoubleClick,
  playheadSec = 0,
  isPlaying = false,
  scrubEnabled = false,
  onScrub,
  snapshot,
  snapshotVersion = 0,
  commit,
  pool = [],
  suggestReplacementsSetting,
  onSuggestReplacementsChange,
  confirmRecompute = true,
  requestConfirmation,
  targetDurationSec = null,
  avgTransitionOverlapSec = 0,
}: CurvePanelProps) {
  const [view, setView] = useState<CurveViewMode>('normal');
  const [templates, setTemplates] = useState<CurveTemplatesResponse | null>(null);
  const [activeTemplateName, setActiveTemplateName] = useState<string | null>(null);
  const [windows, setWindows] = useState<VibeWindowView[]>([]);
  const [overlay, setOverlay] = useState<OverlayState>(OVERLAY_CLOSED);
  const [prompt, setPrompt] = useState<ReplacePrompt | null>(null);
  const [suggestReplacements, setSuggestReplacements] = useState(true);
  const [curveViewportWidth, setCurveViewportWidth] = useState(800);
  const [curvePxPerSecond, setCurvePxPerSecond] = useState(0.08);
  const [curveScrollLeft, setCurveScrollLeft] = useState(0);
  const [curveFitMode, setCurveFitMode] = useState(true);

  const totalSec = slots.reduce((acc, s) => acc + s.track.durationSec, 0);
  const curveDomainSec = Math.max(totalSec, targetDurationSec ?? 0, 1);
  const fitScale = fitPxPerSecond({
    totalSec: curveDomainSec,
    viewportWidth: curveViewportWidth,
  });
  const effectiveCurvePxPerSecond = curveFitMode ? fitScale : curvePxPerSecond;
  const zoomLabel = curveFitMode
    ? 'Fit'
    : `${Math.round(effectiveCurvePxPerSecond * 60)} px/min`;

  const zoomCurve = (direction: 'in' | 'out') => {
    const next = zoomPxPerSecond({
      currentPxPerSecond: effectiveCurvePxPerSecond,
      direction,
      scrollLeft: curveScrollLeft,
      viewportWidth: curveViewportWidth,
      totalSec: curveDomainSec,
    });
    setCurveFitMode(false);
    setCurvePxPerSecond(next.pxPerSecond);
    setCurveScrollLeft(next.scrollLeft);
  };

  const fitCurve = () => {
    setCurveFitMode(true);
    setCurveScrollLeft(0);
  };

  // Settings toggle persists per browser
  useEffect(() => {
    if (suggestReplacementsSetting != null) {
      setSuggestReplacements(suggestReplacementsSetting);
      return;
    }
    const stored = readSuggestSetting();
    if (stored != null) setSuggestReplacements(stored);
  }, [suggestReplacementsSetting]);
  const setSuggest = (on: boolean) => {
    setSuggestReplacements(on);
    writeSuggestSetting(on);
    onSuggestReplacementsChange?.(on);
  };

  const refreshTemplates = useCallback(() => {
    api
      .getCurveTemplates()
      .then(setTemplates)
      .catch(() => setTemplates(null));
  }, []);

  useEffect(() => {
    refreshTemplates();
  }, [refreshTemplates]);

  // Load stored vibe windows once per set, after slots (the time domain)
  // first arrive — a later refetch must never wipe in-session edits.
  const windowsLoadedFor = useRef<number | null>(null);
  useEffect(() => {
    const restored = windowsFromSnapshot(snapshot, totalSec);
    if (restored == null) return;
    windowsLoadedFor.current = setId;
    setWindows(restored);
  }, [setId, snapshot, snapshotVersion, totalSec]);

  useEffect(() => {
    if (snapshot || totalSec <= 0 || windowsLoadedFor.current === setId) return;
    let cancelled = false;
    // Mark eagerly so in-flight fetches dedupe; roll back on failure so a
    // transient error doesn't block the load for the rest of the session.
    windowsLoadedFor.current = setId;
    api
      .getVibeWindows(setId)
      .then((resp) => {
        if (cancelled) return;
        setWindows(
          resp.windows.map((w, i) => ({
            id: `w-${i}-${w.t0_sec}`,
            t0: Math.min(1, w.t0_sec / totalSec),
            t1: Math.min(1, w.t1_sec / totalSec),
            label: w.label,
          })),
        );
      })
      .catch(() => {
        if (cancelled) return;
        if (windowsLoadedFor.current === setId) windowsLoadedFor.current = null;
        setWindows([]);
      });
    return () => {
      cancelled = true;
    };
  }, [setId, snapshot, totalSec]);

  const persistWindows = useCallback(
    (next: VibeWindowView[], label: string) => {
      if (totalSec <= 0) return;
      const save = () =>
        api.putVibeWindows(
          setId,
          next.map((w) => ({
            t0_sec: Math.round(w.t0 * totalSec),
            t1_sec: Math.max(Math.round(w.t0 * totalSec) + 1, Math.round(w.t1 * totalSec)),
            label: w.label,
          })),
        );
      const run = commit ? commit(label, save) : save();
      run.catch(() => {
        /* keep optimistic local state; next successful PUT reconciles */
      });
    },
    [commit, setId, totalSec],
  );

  // --- Target drag ---------------------------------------------------------

  const handleTargetDragEnd = (idx: number, energy: number, anchor: { x: number; y: number }) => {
    const slot = slots[idx];
    if (!slot) return;
    onSlotsChange((prev) => prev.map((s, i) => (i === idx ? { ...s, targetEnergy: energy } : s)));
    const save = () => api.updateSlotTarget(setId, slot.id, energy);
    const run = commit ? commit(`Retarget slot ${idx + 1}`, save) : save();
    run.catch(() => {
      /* optimistic; refetch on next load */
    });
    if (suggestReplacements && Math.abs(energy - slot.track.energy) >= REPLACE_PROMPT_THRESHOLD) {
      // Anchor arrives in viewport coords (converted in CurveEditor onUp).
      setPrompt({ slotIdx: idx, targetEnergy: energy, anchorX: anchor.x, anchorY: anchor.y });
    } else {
      setPrompt(null);
    }
  };

  // --- Templates -----------------------------------------------------------

  const applyTemplate = async (source: { builtin?: string; template_id?: number }, name: string) => {
    if (confirmRecompute && requestConfirmation) {
      const ok = await requestConfirmation({
        title: 'Recompute curve targets?',
        body: (
          <>
            <p>This reruns builder placement against the current curve, pool, and pairings.</p>
            <ul>
              <li>Unlocked slots may reorder and overwrite manual order changes.</li>
              <li>Locked slots stay put.</li>
              <li>Saved pairings are weighted during placement.</li>
              <li>The action is undoable from the topbar or with Ctrl/Cmd+Z.</li>
            </ul>
          </>
        ),
        confirmLabel: 'Yes, recompute',
        kind: 'warning',
      });
      if (!ok) return;
    }
    const midpoints = slots.length > 0 ? slotMidpoints(slots) : undefined;
    const save = async () => {
      const resp = await api.applyCurveTemplate(setId, source, midpoints);
      if (totalSec > 0) {
        const next = resp.windows.map((w, i) => ({
          id: `tw-${i}-${w.t0}`,
          t0: w.t0,
          t1: w.t1,
          label: 'Slow set',
        }));
        await api.putVibeWindows(
          setId,
          next.map((w) => ({
            t0_sec: Math.round(w.t0 * totalSec),
            t1_sec: Math.max(Math.round(w.t0 * totalSec) + 1, Math.round(w.t1 * totalSec)),
            label: w.label,
          })),
        );
      }
      return resp;
    };
    const run = commit ? commit(`Apply curve ${name}`, save) : save();
    run
      .then((resp) => {
        const bySlotId = new Map(resp.targets.map((t) => [t.slot_id, t.target_energy]));
        onSlotsChange((prev) =>
          prev.map((s) => (bySlotId.has(s.id) ? { ...s, targetEnergy: bySlotId.get(s.id) ?? null } : s)),
        );
        // Rebuild vibe windows from the template's slow-window flags
        const next = resp.windows.map((w, i) => ({
          id: `tw-${i}-${w.t0}`,
          t0: w.t0,
          t1: w.t1,
          label: 'Slow set',
        }));
        setWindows(next);
        setActiveTemplateName(name);
        setPrompt(null);
      })
      .catch(() => {
        /* surface stays unchanged on failure */
      });
  };

  const openTemplateEditor = (name: string, isBuiltIn: boolean) => {
    if (isBuiltIn) {
      const tpl = templates?.builtin.find((t) => t.name === name);
      if (!tpl) return;
      setOverlay({ open: true, mode: 'edit', isBuiltIn: true, initial: { name: tpl.name, points: tpl.points } });
    } else {
      const tpl = templates?.user.find((t) => t.name === name);
      if (!tpl) return;
      setOverlay({
        open: true,
        mode: 'edit',
        isBuiltIn: false,
        initial: { id: tpl.id, name: tpl.name, points: tpl.points },
      });
    }
  };

  const saveTemplateNew = (draft: TemplateDraft) => {
    api
      .createCurveTemplate(draft.name, draft.points)
      .then(refreshTemplates)
      .catch(() => {});
  };

  const saveTemplateCurrent = (draft: TemplateDraft) => {
    if (draft.id == null) return;
    api
      .updateCurveTemplate(draft.id, draft.name, draft.points)
      .then(refreshTemplates)
      .catch(() => {});
  };

  const deleteTemplate = (templateId: number) => {
    api
      .deleteCurveTemplate(templateId)
      .then(refreshTemplates)
      .catch(() => {});
  };

  // --- Vibe windows ---------------------------------------------------------

  const addVibeWindow = (preset: VibePreset) => {
    setWindows((prev) => {
      const span = 0.08;
      let t0 = 0.42;
      const sorted = [...prev].sort((a, b) => a.t0 - b.t0);
      for (const s of sorted) {
        if (t0 + span < s.t0) break;
        if (t0 >= s.t0 && t0 < s.t1) t0 = Math.min(1 - span, s.t1 + 0.01);
      }
      const next = [
        ...prev,
        { id: `w-${Date.now()}`, t0, t1: Math.min(1, t0 + span), label: preset.label },
      ];
      persistWindows(next, `Add ${preset.label} window`);
      return next;
    });
  };

  const changeWindow = (id: string, patch: Partial<VibeWindowView>) => {
    setWindows((prev) => prev.map((w) => (w.id === id ? { ...w, ...patch } : w)));
  };

  const commitWindow = () => {
    setWindows((prev) => {
      persistWindows(prev, 'Move vibe window');
      return prev;
    });
  };

  const deleteWindow = (id: string) => {
    setWindows((prev) => {
      const next = prev.filter((w) => w.id !== id);
      persistWindows(next, 'Remove vibe window');
      return next;
    });
  };

  // --- Replacement popover --------------------------------------------------

  const promptSlot = prompt ? slots[prompt.slotIdx] : null;
  const inSetIds = new Set(slots.map((s) => s.track.id));
  const candidates =
    prompt && promptSlot
      ? rankReplacementCandidates(
          prompt.targetEnergy,
          prompt.slotIdx > 0 ? slots[prompt.slotIdx - 1].track : null,
          pool,
          inSetIds,
        )
      : [];

  const handleReplace = (slotId: number, trackId: string) => {
    // Slot/track mutation wires up when the pool ships (#388); until then the
    // popover candidates are informational.
    void slotId;
    void trackId;
    setPrompt(null);
  };

  return (
    <>
      <CurveToolbar
        view={view}
        onViewChange={setView}
        templates={templates}
        activeTemplateName={activeTemplateName}
        zoomLabel={zoomLabel}
        onZoomIn={() => zoomCurve('in')}
        onZoomOut={() => zoomCurve('out')}
        onZoomFit={fitCurve}
        onApplyBuiltin={(name) => applyTemplate({ builtin: name }, name)}
        onApplyUser={(id) => {
          const tpl = templates?.user.find((t) => t.id === id);
          if (tpl) applyTemplate({ template_id: id }, tpl.name);
        }}
        onCreateTemplate={() => setOverlay({ open: true, mode: 'create', initial: null, isBuiltIn: false })}
        onEditTemplate={openTemplateEditor}
        onAddVibeWindow={addVibeWindow}
        suggestReplacements={suggestReplacements}
        onSuggestReplacementsChange={setSuggest}
      />
      <CurveEditor
        slots={slots}
        view={view}
        windows={windows}
        hoveredIdx={hoveredIdx}
        onHover={onHover}
        onBlockClick={onBlockClick}
        onBlockDoubleClick={onBlockDoubleClick}
        playheadSec={playheadSec}
        isPlaying={isPlaying}
        scrubEnabled={scrubEnabled}
        onScrub={onScrub}
        onTargetDragEnd={handleTargetDragEnd}
        onWindowChange={changeWindow}
        onWindowCommit={commitWindow}
        onWindowDelete={deleteWindow}
        targetDurationSec={targetDurationSec}
        avgTransitionOverlapSec={avgTransitionOverlapSec}
        pxPerSecond={effectiveCurvePxPerSecond}
        scrollLeft={curveScrollLeft}
        viewportWidth={curveViewportWidth}
        onScrollLeftChange={(next) => {
          setCurveFitMode(false);
          setCurveScrollLeft(next);
        }}
        onViewportWidthChange={setCurveViewportWidth}
      />
      <CurveTemplateEditorOverlay
        open={overlay.open}
        mode={overlay.mode}
        initial={overlay.initial}
        isBuiltIn={overlay.isBuiltIn}
        onSaveNew={saveTemplateNew}
        onSaveCurrent={saveTemplateCurrent}
        onDelete={deleteTemplate}
        onClose={() => setOverlay(OVERLAY_CLOSED)}
      />
      {prompt && promptSlot && (
        <ReplacePopover
          prompt={prompt}
          slot={promptSlot}
          candidates={candidates}
          onReplace={handleReplace}
          onKeep={() => setPrompt(null)}
          onDismiss={() => setPrompt(null)}
        />
      )}
    </>
  );
}
