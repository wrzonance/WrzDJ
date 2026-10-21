'use client';

/**
 * Curve panel container (#389) — wires the SVG editor, toolbar, template
 * overlay, vibe windows, and replacement popover to the setbuilder API.
 *
 * Targets persist per slot (PATCH on drag-release); templates apply
 * server-side (slot midpoints computed from track durations); vibe windows
 * sync via replace-all PUT. Pool candidates arrive via the `pool` prop.
 */

import { useEffect, useState } from 'react';
import type { SetDocumentSnapshot } from '@/lib/api/types';
import CurveEditor, { type CurveViewMode } from './CurveEditor';
import CurveToolbar from './CurveToolbar';
import CurveTemplateEditorOverlay from './CurveTemplateEditorOverlay';
import type { ConfirmAction } from '../ConfirmActionDialog';
import ReplacePopover from '../pool/ReplacePopover';
import { fitPxPerSecond, zoomPxPerSecond } from './curveViewport';
import { rawTargetSecForSlots } from './targetMath';
import type { SlotView, TrackView } from '../types';
import type { BuilderCommit } from '../useSetDocumentHistory';
import { useCurveTemplateManagement } from './useCurveTemplateManagement';
import { useCurveWindows } from './useCurveWindows';
import { useReplacementSuggestions } from './useReplacementSuggestions';

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
  /** Candidate pool for the replacement popover, loaded with the set workspace. */
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
  const totalSec = slots.reduce((acc, slot) => acc + slot.track.durationSec, 0);
  const {
    windows,
    addWindow: addVibeWindow,
    changeWindow,
    commitWindow,
    deleteWindow,
    replaceWithTemplate,
  } = useCurveWindows({ setId, totalSec, snapshot, snapshotVersion, commit });
  const {
    enabled: suggestReplacements,
    setSuggestReplacements: setSuggest,
    prompt,
    promptSlot,
    candidates,
    handleTargetDragEnd,
    handleReplace,
    dismissPrompt,
    replacementError,
  } = useReplacementSuggestions({
    setId,
    slots,
    pool,
    onSlotsChange,
    commit,
    setting: suggestReplacementsSetting,
    onSettingChange: onSuggestReplacementsChange,
  });
  const {
    templates,
    refreshError: templateRefreshError,
    refreshTemplates,
    activeTemplateName,
    editor,
    openEditor: openTemplateEditor,
    openNewEditor,
    closeEditor,
    saveNew: saveTemplateNew,
    saveCurrent: saveTemplateCurrent,
    remove: deleteTemplate,
    applyTemplate,
    mutationError: templateMutationError,
    mutationPending: templateMutationPending,
    applyError: templateApplyError,
  } = useCurveTemplateManagement({
    setId,
    slots,
    totalSec,
    confirmRecompute,
    requestConfirmation,
    commit,
    onSlotsChange,
    replaceWindows: replaceWithTemplate,
    clearReplacementPrompt: dismissPrompt,
  });
  const [curveViewportWidth, setCurveViewportWidth] = useState(800);
  const [curvePxPerSecond, setCurvePxPerSecond] = useState(0.08);
  const [curveScrollLeft, setCurveScrollLeft] = useState(0);
  const [curveFitMode, setCurveFitMode] = useState(true);

  const rawTargetSec = rawTargetSecForSlots(
    targetDurationSec,
    slots.length,
    avgTransitionOverlapSec,
  );
  const curveDomainSec = Math.max(totalSec, rawTargetSec ?? 0, 1);
  const fitScale = fitPxPerSecond({
    totalSec: curveDomainSec,
    viewportWidth: curveViewportWidth,
  });
  const effectiveCurvePxPerSecond = curveFitMode ? fitScale : curvePxPerSecond;
  const curveMaxScrollLeft = Math.max(
    0,
    curveDomainSec * effectiveCurvePxPerSecond - curveViewportWidth,
  );
  const clampedCurveScrollLeft = Math.max(
    0,
    Math.min(curveMaxScrollLeft, curveScrollLeft),
  );
  const zoomLabel = curveFitMode
    ? 'Fit'
    : `${Math.round(effectiveCurvePxPerSecond * 60)} px/min`;

  const zoomCurve = (direction: 'in' | 'out') => {
    const next = zoomPxPerSecond({
      currentPxPerSecond: effectiveCurvePxPerSecond,
      direction,
      scrollLeft: clampedCurveScrollLeft,
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

  useEffect(() => {
    if (Math.abs(clampedCurveScrollLeft - curveScrollLeft) < 1) return;
    setCurveScrollLeft(clampedCurveScrollLeft);
  }, [clampedCurveScrollLeft, curveScrollLeft]);

  // --- Replacement popover --------------------------------------------------

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
        onCreateTemplate={openNewEditor}
        onEditTemplate={openTemplateEditor}
        onAddVibeWindow={addVibeWindow}
        suggestReplacements={suggestReplacements}
        onSuggestReplacementsChange={setSuggest}
      />
      {templateRefreshError && (
        <p role="alert" style={{ color: 'var(--color-danger)', margin: '0.5rem 0' }}>
          Curve template list could not refresh: {templateRefreshError}{' '}
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void refreshTemplates().catch(() => undefined)}
          >
            Retry list refresh
          </button>
        </p>
      )}
      {templateApplyError && (
        <p role="alert" style={{ color: 'var(--color-danger)', margin: '0.5rem 0' }}>
          {templateApplyError}
        </p>
      )}
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
        scrollLeft={clampedCurveScrollLeft}
        viewportWidth={curveViewportWidth}
        onScrollLeftChange={(next) => {
          const clampedNext = Math.max(0, Math.min(curveMaxScrollLeft, next));
          if (Math.abs(clampedNext - clampedCurveScrollLeft) < 1) return;
          if (curveFitMode) setCurvePxPerSecond(effectiveCurvePxPerSecond);
          setCurveFitMode(false);
          setCurveScrollLeft(clampedNext);
        }}
        onViewportWidthChange={setCurveViewportWidth}
      />
      <CurveTemplateEditorOverlay
        open={editor.open}
        mode={editor.mode}
        initial={editor.initial}
        isBuiltIn={editor.isBuiltIn}
        onSaveNew={saveTemplateNew}
        onSaveCurrent={saveTemplateCurrent}
        onDelete={deleteTemplate}
        onClose={closeEditor}
        mutationError={templateMutationError}
        mutationPending={templateMutationPending}
      />
      {prompt && promptSlot && (
        <ReplacePopover
          prompt={prompt}
          slot={promptSlot}
          candidates={candidates}
          onReplace={handleReplace}
          onKeep={dismissPrompt}
          onDismiss={dismissPrompt}
          error={replacementError}
        />
      )}
    </>
  );
}
