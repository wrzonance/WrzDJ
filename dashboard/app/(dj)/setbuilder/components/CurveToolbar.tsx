'use client';

/**
 * Curve toolbar (#389): Normal / BPM friction / Key friction view switch,
 * template dropdown (built-in + user + create/edit), vibe-window preset
 * dropdown (15 presets), and the replacement-suggestion toggle.
 */

import { useEffect, useRef, useState } from 'react';
import type { CurveTemplatesResponse } from '@/lib/api-types';
import type { CurveViewMode } from './CurveEditor';
import { VIBE_PRESETS, type VibePreset } from './curveMath';
import styles from './curve.module.css';

export interface CurveToolbarProps {
  view: CurveViewMode;
  onViewChange: (view: CurveViewMode) => void;
  templates: CurveTemplatesResponse | null;
  activeTemplateName: string | null;
  zoomLabel: string;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomFit: () => void;
  onApplyBuiltin: (name: string) => void;
  onApplyUser: (templateId: number) => void;
  onCreateTemplate: () => void;
  onEditTemplate: (name: string, isBuiltIn: boolean) => void;
  onAddVibeWindow: (preset: VibePreset) => void;
  suggestReplacements: boolean;
  onSuggestReplacementsChange: (on: boolean) => void;
}

const VIEW_LABELS: Record<CurveViewMode, string> = {
  normal: 'Normal',
  bpm: 'BPM friction',
  key: 'Key friction',
};

function useClickOutside(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open, onClose]);
  return ref;
}

export default function CurveToolbar({
  view,
  onViewChange,
  templates,
  activeTemplateName,
  zoomLabel,
  onZoomIn,
  onZoomOut,
  onZoomFit,
  onApplyBuiltin,
  onApplyUser,
  onCreateTemplate,
  onEditTemplate,
  onAddVibeWindow,
  suggestReplacements,
  onSuggestReplacementsChange,
}: CurveToolbarProps) {
  const [tplOpen, setTplOpen] = useState(false);
  const [vibeOpen, setVibeOpen] = useState(false);
  const tplRef = useClickOutside(tplOpen, () => setTplOpen(false));
  const vibeRef = useClickOutside(vibeOpen, () => setVibeOpen(false));

  return (
    <div className={styles.toolbar} data-testid="curve-toolbar">
      <div className={styles.viewSwitch} role="tablist" aria-label="Curve view mode">
        {(Object.keys(VIEW_LABELS) as CurveViewMode[]).map((mode) => (
          <button
            key={mode}
            role="tab"
            aria-selected={view === mode}
            className={`${styles.viewBtn} ${view === mode ? styles.viewBtnActive : ''}`}
            onClick={() => onViewChange(mode)}
            data-testid={`view-${mode}`}
          >
            {VIEW_LABELS[mode]}
          </button>
        ))}
      </div>

      <div className={styles.zoomControls} aria-label="Curve zoom controls">
        <button
          type="button"
          className={styles.toolbarIconBtn}
          onClick={onZoomOut}
          data-testid="curve-zoom-out"
          aria-label="Zoom out"
          title="Zoom out"
        >
          -
        </button>
        <span className={styles.zoomLabel} data-testid="curve-zoom-label">
          {zoomLabel}
        </span>
        <button
          type="button"
          className={styles.toolbarIconBtn}
          onClick={onZoomIn}
          data-testid="curve-zoom-in"
          aria-label="Zoom in"
          title="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          className={styles.toolbarBtn}
          onClick={onZoomFit}
          data-testid="curve-zoom-fit"
        >
          Fit
        </button>
      </div>

      {/* Template dropdown */}
      <div className={styles.dropdown} ref={tplRef}>
        <button
          className={styles.toolbarBtn}
          onClick={() => setTplOpen((o) => !o)}
          data-testid="template-dropdown-trigger"
        >
          〜 {activeTemplateName ?? 'Pick curve…'} ▾
        </button>
        {tplOpen && (
          <div className={styles.menu} data-testid="template-menu">
            <button
              className={styles.menuItem}
              onClick={() => {
                setTplOpen(false);
                onCreateTemplate();
              }}
              data-testid="template-create-new"
            >
              + Create new curve template…
            </button>
            <div className={styles.menuDivider} />
            <div className={styles.menuSection}>Built-in</div>
            {(templates?.builtin ?? []).map((t) => (
              <div key={t.name} className={styles.menuRow}>
                <button
                  className={styles.menuItem}
                  onClick={() => {
                    setTplOpen(false);
                    onApplyBuiltin(t.name);
                  }}
                  data-testid={`apply-builtin-${t.name}`}
                >
                  {activeTemplateName === t.name ? '● ' : ''}
                  {t.name}
                </button>
                <button
                  className={styles.menuEdit}
                  title="Open built-in as starting point for a new template"
                  onClick={() => {
                    setTplOpen(false);
                    onEditTemplate(t.name, true);
                  }}
                  data-testid={`edit-builtin-${t.name}`}
                >
                  ✎
                </button>
              </div>
            ))}
            {(templates?.user.length ?? 0) > 0 && (
              <>
                <div className={styles.menuDivider} />
                <div className={styles.menuSection}>My templates</div>
                {templates?.user.map((t) => (
                  <div key={t.id} className={styles.menuRow}>
                    <button
                      className={styles.menuItem}
                      onClick={() => {
                        setTplOpen(false);
                        onApplyUser(t.id);
                      }}
                      data-testid={`apply-user-${t.id}`}
                    >
                      {activeTemplateName === t.name ? '● ' : ''}
                      {t.name}
                    </button>
                    <button
                      className={styles.menuEdit}
                      title="Edit this template"
                      onClick={() => {
                        setTplOpen(false);
                        onEditTemplate(t.name, false);
                      }}
                      data-testid={`edit-user-${t.id}`}
                    >
                      ✎
                    </button>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Vibe window dropdown */}
      <div className={styles.dropdown} ref={vibeRef}>
        <button
          className={styles.toolbarBtn}
          onClick={() => setVibeOpen((o) => !o)}
          data-testid="vibe-dropdown-trigger"
        >
          + Vibe window ▾
        </button>
        {vibeOpen && (
          <div className={styles.menu} data-testid="vibe-menu">
            {VIBE_PRESETS.map((p) => (
              <button
                key={p.id}
                className={styles.menuItem}
                onClick={() => {
                  setVibeOpen(false);
                  onAddVibeWindow(p);
                }}
                data-testid={`vibe-preset-${p.id}`}
              >
                {p.label}
                <span className={styles.menuItemHint}>{p.hint}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <label className={styles.toggleLabel} title="Offer pool replacements when a drag-release leaves |target − energy| ≥ 0.8">
        <input
          type="checkbox"
          checked={suggestReplacements}
          onChange={(e) => onSuggestReplacementsChange(e.target.checked)}
          data-testid="suggest-replacements-toggle"
        />
        Suggest replacements
      </label>
    </div>
  );
}
