'use client';

import { SourceIcon, sourceColor, type SourceKind } from '../pool/PoolBadges';
import sharedStyles from '../../setbuilder-shared.module.css';
import importStyles from '../../setbuilder-import.module.css';
import type { PoolImportResult } from '@/lib/api/types';
import type { BuilderCommit } from '../useSetDocumentHistory';

export type ImportKind = SourceKind;

export interface ImportModalProps {
  kind: ImportKind;
  setId: number;
  /** Existing source keys in kind:external_ref format. */
  existingRefs: Set<string>;
  onClose: () => void;
  onImported: (result: PoolImportResult) => void;
  onError: (message: string) => void;
  commit?: BuilderCommit;
}

export function ModalHeader({
  kind,
  title,
  subtitle,
  onClose,
}: {
  kind: string;
  title: string;
  subtitle: string;
  onClose: () => void;
}) {
  return (
    <div className={importStyles.imHeader}>
      <span className={importStyles.imHeaderIcon} style={{ color: sourceColor(kind) }}>
        <SourceIcon kind={kind} size={20} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className={importStyles.imTitle}>{title}</div>
        <div className={importStyles.imSubtitle}>{subtitle}</div>
      </div>
      <button className={sharedStyles.iconBtn} onClick={onClose} aria-label="Close">
        ✕
      </button>
    </div>
  );
}

export function errMessage(e: unknown): string {
  if (e instanceof Error && e.message) return e.message;
  return 'Import failed — try again';
}

export function runImport<T>(
  commit: BuilderCommit | undefined,
  label: string,
  action: () => Promise<T>,
) {
  return commit ? commit(label, action) : action();
}
