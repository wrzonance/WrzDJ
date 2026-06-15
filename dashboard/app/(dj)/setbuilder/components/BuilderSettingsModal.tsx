'use client';

import styles from '../setbuilder.module.css';

export interface BuilderSettings {
  suggestReplacements: boolean;
  confirmRecompute: boolean;
  confirmSlotRemoval: boolean;
  playOnDoubleClick: boolean;
  scrubOnCurveClick: boolean;
  showSlotMarkers: boolean;
  agentChimes: boolean;
  autoExpandPairings: boolean;
}

interface BuilderSettingsModalProps {
  open: boolean;
  onClose: () => void;
  autosave: boolean;
  onAutosaveChange: (value: boolean) => void;
  settings: BuilderSettings;
  onSettingsChange: (settings: BuilderSettings) => void;
}

function ToggleRow({
  title,
  description,
  checked,
  onChange,
}: {
  title: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className={styles.settingsToggle}>
      <span>
        <span className={styles.settingsToggleTitle}>{title}</span>
        <span className={styles.settingsToggleDescription}>{description}</span>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}

export default function BuilderSettingsModal({
  open,
  onClose,
  autosave,
  onAutosaveChange,
  settings,
  onSettingsChange,
}: BuilderSettingsModalProps) {
  if (!open) return null;

  const patch = (partial: Partial<BuilderSettings>) => onSettingsChange({ ...settings, ...partial });

  return (
    <div className={styles.modalWrap}>
      <div className={styles.modalBackdrop} onMouseDown={onClose} />
      <div
        className={styles.settingsModal}
        role="dialog"
        aria-modal="true"
        aria-label="Builder settings"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className={styles.settingsHeader}>
          <h2>Builder settings</h2>
          <button type="button" className="btn btn-sm" onClick={onClose} aria-label="Close settings">
            Close
          </button>
        </div>

        <section className={styles.settingsSection}>
          <h3>Saving</h3>
          <ToggleRow
            title="Autosave"
            description="Save every 30s while the builder document has unsaved changes."
            checked={autosave}
            onChange={onAutosaveChange}
          />
        </section>

        <section className={styles.settingsSection}>
          <h3>Edit prompts</h3>
          <ToggleRow
            title="Energy mismatch prompt"
            description="Offer replacement candidates after large target-energy changes."
            checked={settings.suggestReplacements}
            onChange={(checked) => patch({ suggestReplacements: checked })}
          />
          <ToggleRow
            title="Confirm recompute"
            description="Ask before rerunning builder order or curve recompute actions."
            checked={settings.confirmRecompute}
            onChange={(checked) => patch({ confirmRecompute: checked })}
          />
          <ToggleRow
            title="Confirm before removing a slot"
            description="Ask before destructive removals in the builder document."
            checked={settings.confirmSlotRemoval}
            onChange={(checked) => patch({ confirmSlotRemoval: checked })}
          />
        </section>

        <section className={styles.settingsSection}>
          <h3>Interaction</h3>
          <ToggleRow
            title="Double-click to play"
            description="Start playback from a track row with a double click."
            checked={settings.playOnDoubleClick}
            onChange={(checked) => patch({ playOnDoubleClick: checked })}
          />
          <ToggleRow
            title="Click curve to scrub"
            description="Let curve clicks move the transport position."
            checked={settings.scrubOnCurveClick}
            onChange={(checked) => patch({ scrubOnCurveClick: checked })}
          />
          <ToggleRow
            title="Show slot markers"
            description="Show each slot position on the curve editor."
            checked={settings.showSlotMarkers}
            onChange={(checked) => patch({ showSlotMarkers: checked })}
          />
        </section>

        <section className={styles.settingsSection}>
          <h3>Agent</h3>
          <ToggleRow
            title="Agent chimes"
            description="Play subtle sound cues for agent suggestions."
            checked={settings.agentChimes}
            onChange={(checked) => patch({ agentChimes: checked })}
          />
          <ToggleRow
            title="Auto-expand pairings"
            description="Open new pairing suggestions as the agent creates them."
            checked={settings.autoExpandPairings}
            onChange={(checked) => patch({ autoExpandPairings: checked })}
          />
        </section>
      </div>
    </div>
  );
}
