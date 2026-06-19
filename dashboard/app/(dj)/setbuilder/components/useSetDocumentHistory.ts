'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { SetDocumentSnapshot } from '@/lib/api-types';

const AUTOSAVE_KEY = 'wrzdj.setbuilder.autosave';

export type BuilderCommit = <T>(
  label: string,
  action: () => Promise<T> | T,
  shouldRecord?: (result: T) => boolean,
) => Promise<T>;

interface HistoryEntry {
  label: string;
  snapshot: SetDocumentSnapshot;
}

interface UseSetDocumentHistoryOptions {
  enabled?: boolean;
}

function readAutosave(): boolean {
  try {
    return window.localStorage.getItem(AUTOSAVE_KEY) !== 'false';
  } catch {
    return true;
  }
}

function writeAutosave(value: boolean): void {
  try {
    window.localStorage.setItem(AUTOSAVE_KEY, String(value));
  } catch {
    // Best-effort browser preference.
  }
}

function cloneSnapshot(snapshot: SetDocumentSnapshot): SetDocumentSnapshot {
  return JSON.parse(JSON.stringify(snapshot)) as SetDocumentSnapshot;
}

export function useSetDocumentHistory(
  setId: number,
  { enabled = true }: UseSetDocumentHistoryOptions = {},
) {
  const [snapshot, setSnapshot] = useState<SetDocumentSnapshot | null>(null);
  const [snapshotVersion, setSnapshotVersion] = useState(0);
  const [undoStack, setUndoStack] = useState<HistoryEntry[]>([]);
  const [redoStack, setRedoStack] = useState<HistoryEntry[]>([]);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [autosave, setAutosaveState] = useState(true);
  const snapshotRef = useRef<SetDocumentSnapshot | null>(null);
  const operationInFlightRef = useRef(false);

  const beginOperation = useCallback(() => {
    if (operationInFlightRef.current) return false;
    operationInFlightRef.current = true;
    return true;
  }, []);

  const finishOperation = useCallback(() => {
    operationInFlightRef.current = false;
  }, []);

  const publishSnapshot = useCallback((next: SetDocumentSnapshot) => {
    snapshotRef.current = cloneSnapshot(next);
    setSnapshot(next);
    setSnapshotVersion((v) => v + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setSaveError(null);
    setUndoStack([]);
    setRedoStack([]);
    snapshotRef.current = null;
    setSnapshot(null);
    setSnapshotVersion(0);
    setLastSavedAt(null);
    setIsDirty(false);
    setAutosaveState(readAutosave());
    if (!enabled) {
      return () => {
        cancelled = true;
      };
    }
    api
      .getSetDocument(setId)
      .then((doc) => {
        if (cancelled) return;
        publishSnapshot(doc);
        setLastSavedAt(new Date());
        setIsDirty(false);
      })
      .catch(() => {
        if (!cancelled) setSaveError('Failed to load document history');
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, publishSnapshot, setId]);

  useEffect(() => {
    if (!toast) return;
    const handle = window.setTimeout(() => setToast(null), 2500);
    return () => window.clearTimeout(handle);
  }, [toast]);

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!isDirty && !isSaving && !saveError) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [isDirty, isSaving, saveError]);

  const fetchCurrent = useCallback(async () => {
    if (!enabled) throw new Error('Document history is not ready');
    if (snapshotRef.current) return cloneSnapshot(snapshotRef.current);
    const current = await api.getSetDocument(setId);
    publishSnapshot(current);
    return cloneSnapshot(current);
  }, [enabled, publishSnapshot, setId]);

  const commit: BuilderCommit = useCallback(
    async (label, action, shouldRecord = () => true) => {
      if (!beginOperation()) {
        throw new Error('Another document history operation is already in progress');
      }
      try {
        const before = await fetchCurrent();
        setIsSaving(true);
        setIsDirty(true);
        setSaveError(null);
        const result = await action();
        const after = await api.getSetDocument(setId);
        if (shouldRecord(result)) {
          setUndoStack((prev) => [...prev, { label, snapshot: before }].slice(-50));
          setRedoStack([]);
        }
        publishSnapshot(after);
        setLastSavedAt(new Date());
        setIsDirty(false);
        return result;
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : 'Save failed');
        throw error;
      } finally {
        setIsSaving(false);
        finishOperation();
      }
    },
    [beginOperation, fetchCurrent, finishOperation, publishSnapshot, setId],
  );

  const restore = useCallback(
    async (direction: 'undo' | 'redo') => {
      const source = direction === 'undo' ? undoStack : redoStack;
      const entry = source[source.length - 1];
      if (!entry) return;
      if (!beginOperation()) return;
      try {
        const current = await fetchCurrent();
        setIsSaving(true);
        setIsDirty(true);
        setSaveError(null);
        const restored = await api.putSetDocument(setId, entry.snapshot);
        if (direction === 'undo') {
          setUndoStack((prev) => prev.slice(0, -1));
          setRedoStack((prev) => [...prev, { label: entry.label, snapshot: current }].slice(-50));
          setToast(`Undid ${entry.label}`);
        } else {
          setRedoStack((prev) => prev.slice(0, -1));
          setUndoStack((prev) => [...prev, { label: entry.label, snapshot: current }].slice(-50));
          setToast(`Redid ${entry.label}`);
        }
        publishSnapshot(restored);
        setLastSavedAt(new Date());
        setIsDirty(false);
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : 'Restore failed');
      } finally {
        setIsSaving(false);
        finishOperation();
      }
    },
    [beginOperation, fetchCurrent, finishOperation, publishSnapshot, redoStack, setId, undoStack],
  );

  const undo = useCallback(() => restore('undo'), [restore]);
  const redo = useCallback(() => restore('redo'), [restore]);

  const saveNow = useCallback(async () => {
    if (!beginOperation()) return;
    try {
      const current = await fetchCurrent();
      setIsSaving(true);
      setIsDirty(true);
      setSaveError(null);
      const saved = await api.putSetDocument(setId, current);
      publishSnapshot(saved);
      setLastSavedAt(new Date());
      setIsDirty(false);
      setToast('Saved');
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Save failed');
    } finally {
      setIsSaving(false);
      finishOperation();
    }
  }, [beginOperation, fetchCurrent, finishOperation, publishSnapshot, setId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName?.toLowerCase();
      if (tagName === 'input' || tagName === 'textarea' || target?.isContentEditable) return;
      const mod = event.metaKey || event.ctrlKey;
      if (!mod) return;
      const key = event.key.toLowerCase();
      if (key === 'z' && event.shiftKey) {
        event.preventDefault();
        void redo();
      } else if (key === 'z') {
        event.preventDefault();
        void undo();
      } else if (key === 'y') {
        event.preventDefault();
        void redo();
      } else if (key === 's') {
        event.preventDefault();
        void saveNow();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [redo, saveNow, undo]);

  const setAutosave = useCallback((value: boolean) => {
    setAutosaveState(value);
    writeAutosave(value);
  }, []);

  useEffect(() => {
    if (!autosave) return;
    const handle = window.setInterval(() => {
      if (!isDirty || isSaving) return;
      void saveNow();
    }, 30_000);
    return () => window.clearInterval(handle);
  }, [autosave, isDirty, isSaving, saveNow]);

  return useMemo(
    () => ({
      snapshot,
      snapshotVersion,
      commit,
      undo,
      redo,
      saveNow,
      undoDepth: undoStack.length,
      redoDepth: redoStack.length,
      nextUndoLabel: undoStack.at(-1)?.label ?? null,
      nextRedoLabel: redoStack.at(-1)?.label ?? null,
      isSaving,
      isDirty,
      saveError,
      lastSavedAt,
      autosave,
      setAutosave,
      toast,
    }),
    [
      autosave,
      commit,
      isSaving,
      isDirty,
      lastSavedAt,
      redo,
      redoStack,
      saveError,
      saveNow,
      setAutosave,
      snapshot,
      snapshotVersion,
      toast,
      undo,
      undoStack,
    ],
  );
}
