'use client';

import type { ReactNode } from 'react';
import styles from '../setbuilder.module.css';

export interface ConfirmAction {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  kind?: 'warning' | 'danger' | 'neutral';
}

interface ConfirmActionDialogProps {
  action: ConfirmAction | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function ConfirmActionDialog({
  action,
  onCancel,
  onConfirm,
}: ConfirmActionDialogProps) {
  if (!action) return null;
  const kind = action.kind ?? 'danger';
  const iconClass =
    kind === 'warning'
      ? styles.confirmIconWarning
      : kind === 'danger'
        ? styles.confirmIconDanger
        : styles.confirmIconNeutral;
  return (
    <div className={styles.modalWrap}>
      <div className={styles.modalBackdrop} onMouseDown={onCancel} />
      <div
        className={styles.confirmDialog}
        role="alertdialog"
        aria-modal="true"
        aria-label={action.title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className={styles.confirmHeader}>
          <span className={`${styles.confirmIcon} ${iconClass}`}>
            {kind === 'warning' ? '!' : kind === 'danger' ? '×' : 'i'}
          </span>
          <h2>{action.title}</h2>
        </div>
        <div className={styles.confirmBody}>{action.body}</div>
        <div className={styles.confirmActions}>
          <button type="button" className="btn btn-sm" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className={`btn btn-sm ${kind === 'danger' ? styles.dangerBtn : styles.warningBtn}`}
            onClick={onConfirm}
          >
            {action.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
