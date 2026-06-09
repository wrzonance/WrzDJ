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
import type { CurveTemplatesResponse } from '@/lib/api-types';
import CurveEditor, { type CurveViewMode } from './CurveEditor';
import CurveToolbar from './CurveToolbar';
import CurveTemplateEditorOverlay, { type TemplateDraft } from './CurveTemplateEditorOverlay';
import ReplacePopover, { type ReplacePrompt } from './ReplacePopover';
import {
  REPLACE_PROMPT_THRESHOLD,
  rankReplacementCandidates,
  slotMidpoints,
  type VibePreset,
} from './curveMath';
import type { SlotView, TrackView, VibeWindowView } from './types';

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

export interface CurvePanelProps {
  setId: number;
  slots: SlotView[];
  onSlotsChange: (updater: (prev: SlotView[]) => SlotView[]) => void;
  hoveredIdx: number | null;
  onHover: (idx: number | null) => void;
  onBlockClick: (idx: number) => void;
  /** Candidate pool for the replacement popover (#388 feeds this). */
  pool?: TrackView[];
}

export default function CurvePanel({
  setId,
  slots,
  onSlotsChange,
  hoveredIdx,
  onHover,
  onBlockClick,
  pool = [],
}: CurvePanelProps) {
  const [view, setView] = useState<CurveViewMode>('normal');
  const [templates, setTemplates] = useState<CurveTemplatesResponse | null>(null);
  const [activeTemplateName, setActiveTemplateName] = useState<string | null>(null);
  const [windows, setWindows] = useState<VibeWindowView[]>([]);
  const [overlay, setOverlay] = useState<OverlayState>(OVERLAY_CLOSED);
  const [prompt, setPrompt] = useState<ReplacePrompt | null>(null);
  const [suggestReplacements, setSuggestReplacements] = useState(true);

  const totalSec = slots.reduce((acc, s) => acc + s.track.durationSec, 0);

  // Settings toggle persists per browser
  useEffect(() => {
    const stored = readSuggestSetting();
    if (stored != null) setSuggestReplacements(stored);
  }, []);
  const setSuggest = (on: boolean) => {
    setSuggestReplacements(on);
    writeSuggestSetting(on);
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
    if (totalSec <= 0 || windowsLoadedFor.current === setId) return;
    windowsLoadedFor.current = setId;
    api
      .getVibeWindows(setId)
      .then((resp) => {
        setWindows(
          resp.windows.map((w, i) => ({
            id: `w-${i}-${w.t0_sec}`,
            t0: Math.min(1, w.t0_sec / totalSec),
            t1: Math.min(1, w.t1_sec / totalSec),
            label: w.label,
          })),
        );
      })
      .catch(() => setWindows([]));
  }, [setId, totalSec]);

  const persistWindows = useCallback(
    (next: VibeWindowView[]) => {
      if (totalSec <= 0) return;
      api
        .putVibeWindows(
          setId,
          next.map((w) => ({
            t0_sec: Math.round(w.t0 * totalSec),
            t1_sec: Math.max(Math.round(w.t0 * totalSec) + 1, Math.round(w.t1 * totalSec)),
            label: w.label,
          })),
        )
        .catch(() => {
          /* keep optimistic local state; next successful PUT reconciles */
        });
    },
    [setId, totalSec],
  );

  // --- Target drag ---------------------------------------------------------

  const handleTargetDragEnd = (idx: number, energy: number, anchor: { x: number; y: number }) => {
    const slot = slots[idx];
    if (!slot) return;
    onSlotsChange((prev) => prev.map((s, i) => (i === idx ? { ...s, targetEnergy: energy } : s)));
    api.updateSlotTarget(setId, slot.id, energy).catch(() => {
      /* optimistic; refetch on next load */
    });
    if (suggestReplacements && Math.abs(energy - slot.track.energy) >= REPLACE_PROMPT_THRESHOLD) {
      // Anchor is in SVG viewbox coords; position near the pointer instead.
      setPrompt({ slotIdx: idx, targetEnergy: energy, anchorX: anchor.x, anchorY: anchor.y });
    } else {
      setPrompt(null);
    }
  };

  // --- Templates -----------------------------------------------------------

  const applyTemplate = (source: { builtin?: string; template_id?: number }, name: string) => {
    const midpoints = slots.length > 0 ? slotMidpoints(slots) : undefined;
    api
      .applyCurveTemplate(setId, source, midpoints)
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
        persistWindows(next);
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
      persistWindows(next);
      return next;
    });
  };

  const changeWindow = (id: string, patch: Partial<VibeWindowView>) => {
    setWindows((prev) => prev.map((w) => (w.id === id ? { ...w, ...patch } : w)));
  };

  const commitWindow = () => {
    setWindows((prev) => {
      persistWindows(prev);
      return prev;
    });
  };

  const deleteWindow = (id: string) => {
    setWindows((prev) => {
      const next = prev.filter((w) => w.id !== id);
      persistWindows(next);
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
        onTargetDragEnd={handleTargetDragEnd}
        onWindowChange={changeWindow}
        onWindowCommit={commitWindow}
        onWindowDelete={deleteWindow}
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
