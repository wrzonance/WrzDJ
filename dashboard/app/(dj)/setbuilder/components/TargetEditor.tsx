'use client';

import { useEffect, useRef } from 'react';
import {
  TARGET_PRESETS,
  formatDelta,
  formatTimecode,
  type TargetProjection,
  type TargetSettings,
} from './targetMath';
import styles from '../setbuilder.module.css';

interface TargetEditorProps {
  settings: TargetSettings;
  projection: TargetProjection | null;
  dirty: boolean;
  saving: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSettingsChange: (settings: TargetSettings) => void;
  onSave: () => void;
  onUndo: () => void;
}

function hoursMinutes(sec: number | null): { hours: number; minutes: number } {
  if (sec == null) return { hours: 0, minutes: 0 };
  const totalMinutes = Math.max(0, Math.round(sec / 60));
  return { hours: Math.floor(totalMinutes / 60), minutes: totalMinutes % 60 };
}

function durationFromParts(hours: number, minutes: number): number | null {
  const safeHours = Math.max(0, Math.min(24, hours));
  const safeMinutes = Math.max(0, Math.min(59, minutes));
  const total = safeHours * 3600 + safeMinutes * 60;
  return total > 0 ? total : null;
}

export default function TargetEditor({
  settings,
  projection,
  dirty,
  saving,
  open,
  onOpenChange,
  onSettingsChange,
  onSave,
  onUndo,
}: TargetEditorProps) {
  const ref = useRef<HTMLDivElement>(null);
  const parts = hoursMinutes(settings.targetDurationSec);
  const tier = projection?.tier ?? 'none';
  const totalMinutes = Math.round((settings.targetDurationSec ?? 0) / 60);

  const updateTargetPart = (patch: Partial<{ hours: number; minutes: number }>) => {
    const next = { ...parts, ...patch };
    onSettingsChange({ ...settings, targetDurationSec: durationFromParts(next.hours, next.minutes) });
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (ev: MouseEvent) => {
      if (ref.current && !ref.current.contains(ev.target as Node)) onOpenChange(false);
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') onOpenChange(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onOpenChange]);

  const cancel = () => {
    onUndo();
    onOpenChange(false);
  };

  const apply = () => {
    onSave();
    onOpenChange(false);
  };

  return (
    <div className={styles.targetWrap} ref={ref}>
      <button
        type="button"
        className={`${styles.targetPill} ${styles[`targetTier_${tier}`]}`}
        onClick={() => onOpenChange(!open)}
        aria-expanded={open}
        data-testid="target-pill"
        title="Click to edit the target set length"
      >
        <span className={styles.targetIcon} aria-hidden="true">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="5" />
            <circle cx="12" cy="12" r="1.5" fill="currentColor" />
          </svg>
        </span>
        <span>{formatTimecode(settings.targetDurationSec)}</span>
        <span className={styles.targetPillLabel}>target</span>
        {dirty ? <span className={styles.targetDirty} aria-label="Unsaved target changes" /> : null}
      </button>

      {open ? (
        <div className={styles.targetPopover} data-testid="target-popover">
          <div className={styles.targetArrow} />
          <div className={styles.targetPopoverHeader}>
            <div>
              <div className={styles.targetTitle}>Set length target</div>
              <div className={styles.targetSub}>
                Used for pacing guidance. Actual playing time varies with cuts and transitions.
              </div>
            </div>
          </div>

          <div className={styles.targetSectionLabel}>Common</div>
          <div className={styles.targetPresetGrid}>
            {TARGET_PRESETS.map((preset) => (
              <button
                type="button"
                key={preset.id}
                className={`${styles.targetPreset} ${totalMinutes === preset.seconds / 60 ? styles.targetPresetActive : ''}`}
                onClick={() => onSettingsChange({ ...settings, targetDurationSec: preset.seconds })}
                data-testid={`target-preset-${preset.id}`}
              >
                <span>{preset.label}</span>
                <small>{preset.hint}</small>
              </button>
            ))}
          </div>

          <div className={styles.targetSectionLabel}>Custom</div>
          <div className={styles.targetInputs}>
            <label>
              <span>hr</span>
              <input
                type="number"
                min={0}
                max={12}
                value={parts.hours}
                onChange={(ev) => updateTargetPart({ hours: Number(ev.target.value) })}
              />
            </label>
            <label>
              <span>min</span>
              <input
                type="number"
                min={0}
                max={59}
                value={parts.minutes}
                onChange={(ev) => updateTargetPart({ minutes: Number(ev.target.value) })}
              />
            </label>
            <span className={styles.targetEquivalent}>
              = {formatTimecode(settings.targetDurationSec)}
            </span>
          </div>

          <div className={styles.targetSectionLabel}>Avg transition overlap</div>
          <div className={styles.targetHelp}>
            DJs blend tracks rather than gap them. Estimate seconds of overlap per transition.
          </div>
          <label className={styles.targetSlider}>
            <span>
              <b>{settings.avgTransitionOverlapSec}s</b>
            </span>
            <input
              type="range"
              min={0}
              max={32}
              value={settings.avgTransitionOverlapSec}
              onChange={(ev) =>
                onSettingsChange({
                  ...settings,
                  avgTransitionOverlapSec: Number(ev.target.value),
                })
              }
            />
          </label>

          <div className={styles.targetProjectionCard}>
            {projection ? (
              <>
                <div className={styles.targetProjectionRow}>
                  <span>Sum of track durations</span>
                  <strong>{formatTimecode(projection.rawTotalSec)}</strong>
                </div>
                <div className={styles.targetProjectionRow}>
                  <span>- {projection.transitionCount} transitions x {settings.avgTransitionOverlapSec}s</span>
                  <strong className={styles.targetMuted}>-{formatTimecode(projection.transitionOverlapSec)}</strong>
                </div>
                <div className={`${styles.targetProjectionRow} ${styles.targetProjectionEffective}`}>
                  <span>Projected playing time</span>
                  <strong>{formatTimecode(projection.effectiveSec)}</strong>
                </div>
                <div className={styles.targetProjectionRow}>
                  <span>vs target {formatTimecode(settings.targetDurationSec)}</span>
                  <strong className={`${styles.targetDeltaValue} ${styles[`targetTier_${tier}`]}`}>
                    {formatDelta(projection.deltaSec)}
                  </strong>
                </div>
              </>
            ) : (
              <div className={styles.targetProjectionRow}>
                <span>Projection</span>
                <strong>No tracks</strong>
              </div>
            )}
          </div>

          <div className={styles.targetActions}>
            <button type="button" className="btn btn-ghost btn-sm" onClick={cancel} disabled={saving}>
              Cancel
            </button>
            <button
              type="button"
              className={`btn btn-sm ${dirty ? 'btn-primary' : 'btn-ghost'}`}
              onClick={apply}
              disabled={!dirty || saving}
            >
              {saving ? 'Saving...' : 'Apply'}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
