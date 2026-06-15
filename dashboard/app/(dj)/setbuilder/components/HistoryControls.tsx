import styles from '../setbuilder.module.css';

interface HistoryControlsProps {
  undoDepth: number;
  redoDepth: number;
  nextUndoLabel: string | null;
  nextRedoLabel: string | null;
  onUndo: () => void;
  onRedo: () => void;
  onSettings: () => void;
  isSaving: boolean;
}

export default function HistoryControls({
  undoDepth,
  redoDepth,
  nextUndoLabel,
  nextRedoLabel,
  onUndo,
  onRedo,
  onSettings,
  isSaving,
}: HistoryControlsProps) {
  return (
    <span className={styles.historyControls}>
      <button
        type="button"
        className={styles.historyIconButton}
        onClick={onUndo}
        disabled={!undoDepth || isSaving}
        title={nextUndoLabel ? `Undo: ${nextUndoLabel}` : 'Undo'}
        aria-label={nextUndoLabel ? `Undo: ${nextUndoLabel}` : 'Undo'}
      >
        ↶ <span className={styles.depthBadge}>{undoDepth}</span>
      </button>
      <button
        type="button"
        className={styles.historyIconButton}
        onClick={onRedo}
        disabled={!redoDepth || isSaving}
        title={nextRedoLabel ? `Redo: ${nextRedoLabel}` : 'Redo'}
        aria-label={nextRedoLabel ? `Redo: ${nextRedoLabel}` : 'Redo'}
      >
        ↷ <span className={styles.depthBadge}>{redoDepth}</span>
      </button>
      <button
        type="button"
        className={styles.historyIconButton}
        onClick={onSettings}
        aria-label="Open builder settings"
        title="Builder settings"
      >
        ⚙
      </button>
    </span>
  );
}
