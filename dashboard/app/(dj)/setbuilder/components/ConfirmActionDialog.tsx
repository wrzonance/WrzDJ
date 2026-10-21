'use client';

import type { ReactNode } from 'react';

import dialogStyles from '../setbuilder-dialogs.module.css';
import sharedStyles from '../setbuilder-shared.module.css';

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
      ? dialogStyles.confirmIconWarning
      : kind === 'danger'
        ? dialogStyles.confirmIconDanger
        : dialogStyles.confirmIconNeutral;
  return (
    <div className={sharedStyles.modalWrap}>
      <div className={sharedStyles.modalBackdrop} onMouseDown={onCancel} />
      <div
        className={dialogStyles.confirmDialog}
        role="alertdialog"
        aria-modal="true"
        aria-label={action.title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className={dialogStyles.confirmHeader}>
          <span className={`${dialogStyles.confirmIcon} ${iconClass}`}>
            {kind === 'warning' ? '!' : kind === 'danger' ? '×' : 'i'}
          </span>
          <h2>{action.title}</h2>
        </div>
        <div className={dialogStyles.confirmBody}>{action.body}</div>
        <div className={dialogStyles.confirmActions}>
          <button type="button" className="btn btn-sm" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className={`btn btn-sm ${kind === 'danger' ? sharedStyles.dangerBtn : sharedStyles.warningBtn}`}
            onClick={onConfirm}
          >
            {action.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
