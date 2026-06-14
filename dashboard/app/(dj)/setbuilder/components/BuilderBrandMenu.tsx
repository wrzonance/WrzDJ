'use client';

import { useEffect, useRef, useState } from 'react';
import styles from '../setbuilder.module.css';

function formatAgo(date: Date | null, now: number): string {
  if (!date) return 'just now';
  const seconds = Math.max(0, Math.floor((now - date.getTime()) / 1000));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

interface BuilderBrandMenuProps {
  name: string;
  isDirty: boolean;
  isSaving: boolean;
  saveError: string | null;
  lastSavedAt: Date | null;
  onSave: () => void;
  onSettings: () => void;
}

export default function BuilderBrandMenu({
  name,
  isDirty,
  isSaving,
  saveError,
  lastSavedAt,
  onSave,
  onSettings,
}: BuilderBrandMenuProps) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const ref = useRef<HTMLDivElement | null>(null);
  const dirty = isDirty || isSaving || Boolean(saveError);
  const label = dirty ? 'Unsaved changes' : 'All saved';
  const sublabel = saveError
    ? saveError
    : dirty
      ? 'Click to save · Ctrl/Cmd+S'
      : `${formatAgo(lastSavedAt, now)}`;

  useEffect(() => {
    const handle = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const save = () => {
    setOpen(false);
    onSave();
  };

  return (
    <div className={styles.brandMenuWrap} ref={ref}>
      <button
        type="button"
        className={styles.brandButton}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className={styles.brandTitle}>{name}</span>
        <span className={`${styles.saveDot} ${dirty ? styles.saveDotDirty : ''}`} />
      </button>
      {open && (
        <div className={styles.brandMenu} role="menu">
          <button
            type="button"
            className={`${styles.brandMenuItem} ${styles.brandSaveRow}`}
            onClick={save}
            disabled={isSaving}
            role="menuitem"
          >
            <span className={`${styles.saveDot} ${dirty ? styles.saveDotDirty : ''}`} />
            <span>
              <span className={styles.saveLabel}>{label}</span>
              <span className={styles.saveSub}>{sublabel}</span>
            </span>
          </button>
          <button
            type="button"
            className={styles.brandMenuItem}
            onClick={() => {
              setOpen(false);
              onSettings();
            }}
            role="menuitem"
          >
            Settings
          </button>
        </div>
      )}
    </div>
  );
}
