'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { SetDocumentSnapshot } from '@/lib/api/types';
import type { BuilderCommit } from '../useSetDocumentHistory';
import type { VibeWindowView } from '../types';
import type { VibePreset } from './curveMath';

interface UseCurveWindowsOptions {
  setId: number;
  totalSec: number;
  snapshot?: SetDocumentSnapshot | null;
  snapshotVersion: number;
  commit?: BuilderCommit;
}

function windowsFromSnapshot(
  snapshot: SetDocumentSnapshot | null | undefined,
  totalSec: number,
): VibeWindowView[] | null {
  if (!snapshot || totalSec <= 0) return null;
  const rows = [...snapshot.curve_points].sort((a, b) => a.id - b.id);
  const windows: VibeWindowView[] = [];
  let open: (typeof rows)[number] | null = null;
  for (const row of rows) {
    if (row.is_slow_window_start) open = row;
    else if (row.is_slow_window_end && open) {
      windows.push({
        id: `sw-${open.id}-${row.id}`,
        t0: Math.min(1, open.position_sec / totalSec),
        t1: Math.min(1, row.position_sec / totalSec),
        label: open.label ?? 'Vibe window',
      });
      open = null;
    }
  }
  return windows;
}

export function useCurveWindows({
  setId,
  totalSec,
  snapshot,
  snapshotVersion,
  commit,
}: UseCurveWindowsOptions) {
  const [windows, setWindows] = useState<VibeWindowView[]>([]);
  const windowsRef = useRef(windows);
  const editVersions = useRef(new Map<number, number>());
  const loadsInFlight = useRef(new Set<number>());
  const pendingWrites = useRef(new Map<number, { label: string; windows: VibeWindowView[] }>());
  const stateSetId = useRef(setId);
  const initialSnapshotLoadedFor = useRef<number | null>(null);
  const snapshotVersionAppliedFor = useRef(new Map<number, number>());
  const editedBeforeSnapshotFor = useRef<number | null>(null);
  const windowsLoadedFor = useRef<number | null>(null);
  const nextWindowId = useRef(0);

  const replaceWindows = useCallback((next: VibeWindowView[]) => {
    windowsRef.current = next;
    setWindows(next);
  }, []);
  const editVersionFor = useCallback(
    (targetSetId: number) => editVersions.current.get(targetSetId) ?? 0,
    [],
  );
  const markWindowsEdited = useCallback(() => {
    editVersions.current.set(setId, editVersionFor(setId) + 1);
    if (!snapshot) editedBeforeSnapshotFor.current = setId;
  }, [editVersionFor, setId, snapshot]);

  const persistWindows = useCallback(
    (next: VibeWindowView[], label: string) => {
      if (totalSec <= 0) return;
      if (loadsInFlight.current.has(setId)) {
        pendingWrites.current.set(setId, { label, windows: next });
        return;
      }
      const save = () =>
        api.putVibeWindows(
          setId,
          next.map((window) => ({
            t0_sec: Math.round(window.t0 * totalSec),
            t1_sec: Math.max(
              Math.round(window.t0 * totalSec) + 1,
              Math.round(window.t1 * totalSec),
            ),
            label: window.label,
          })),
        );
      const run = commit ? commit(label, save) : save();
      run.catch(() => {
        /* Keep optimistic local state; the next successful PUT reconciles it. */
      });
    },
    [commit, setId, totalSec],
  );

  useEffect(() => {
    if (stateSetId.current === setId) return;
    stateSetId.current = setId;
    initialSnapshotLoadedFor.current = null;
    editedBeforeSnapshotFor.current = null;
    windowsLoadedFor.current = null;
    replaceWindows([]);
  }, [replaceWindows, setId]);

  useEffect(() => {
    const restored = windowsFromSnapshot(snapshot, totalSec);
    if (restored == null) return;
    if (
      initialSnapshotLoadedFor.current === setId &&
      snapshotVersionAppliedFor.current.get(setId) === snapshotVersion
    ) {
      return;
    }
    windowsLoadedFor.current = setId;
    snapshotVersionAppliedFor.current.set(setId, snapshotVersion);
    if (initialSnapshotLoadedFor.current !== setId) {
      initialSnapshotLoadedFor.current = setId;
      if (editedBeforeSnapshotFor.current === setId) {
        editedBeforeSnapshotFor.current = null;
        loadsInFlight.current.delete(setId);
        const pending = pendingWrites.current.get(setId);
        pendingWrites.current.delete(setId);
        const next = [...restored, ...windowsRef.current];
        replaceWindows(next);
        persistWindows(next, pending?.label ?? 'Add vibe window');
        return;
      }
    }
    replaceWindows(restored);
  }, [persistWindows, replaceWindows, setId, snapshot, snapshotVersion, totalSec]);

  useEffect(() => {
    if (snapshot || totalSec <= 0 || windowsLoadedFor.current === setId) return;
    let cancelled = false;
    const editVersionAtLoad = editVersionFor(setId);
    // Mark eagerly to dedupe concurrent loads; retry after a transient failure.
    windowsLoadedFor.current = setId;
    loadsInFlight.current.add(setId);
    api
      .getVibeWindows(setId)
      .then((response) => {
        const loaded = response.windows.map((window, index) => ({
          id: `w-${index}-${window.t0_sec}`,
          t0: Math.min(1, window.t0_sec / totalSec),
          t1: Math.min(1, window.t1_sec / totalSec),
          label: window.label,
        }));
        const pending = pendingWrites.current.get(setId);
        if (cancelled) {
          loadsInFlight.current.delete(setId);
          if (!pending || editVersionFor(setId) === editVersionAtLoad) return;
          pendingWrites.current.delete(setId);
          persistWindows([...loaded, ...pending.windows], pending.label);
          return;
        }
        loadsInFlight.current.delete(setId);
        if (editVersionFor(setId) !== editVersionAtLoad) {
          if (!pending) return;
          pendingWrites.current.delete(setId);
          const next = [...loaded, ...pending.windows];
          replaceWindows(next);
          persistWindows(next, pending.label);
          return;
        }
        replaceWindows(loaded);
      })
      .catch(() => {
        if (cancelled) return;
        loadsInFlight.current.delete(setId);
        if (windowsLoadedFor.current === setId) windowsLoadedFor.current = null;
        if (editVersionFor(setId) === editVersionAtLoad) {
          replaceWindows([]);
          return;
        }
        const pending = pendingWrites.current.get(setId);
        if (pending) {
          pendingWrites.current.delete(setId);
          persistWindows(pending.windows, pending.label);
        }
      });
    return () => {
      cancelled = true;
      loadsInFlight.current.delete(setId);
    };
  }, [editVersionFor, persistWindows, replaceWindows, setId, snapshot, totalSec]);

  const addWindow = useCallback(
    (preset: VibePreset) => {
      const span = 0.08;
      let t0 = 0.42;
      const current = windowsRef.current;
      const sorted = [...current].sort((a, b) => a.t0 - b.t0);
      for (const window of sorted) {
        if (t0 + span < window.t0) break;
        if (t0 >= window.t0 && t0 < window.t1) t0 = Math.min(1 - span, window.t1 + 0.01);
      }
      const next = [
        ...current,
        {
          id: `w-${Date.now()}-${nextWindowId.current++}`,
          t0,
          t1: Math.min(1, t0 + span),
          label: preset.label,
        },
      ];
      markWindowsEdited();
      replaceWindows(next);
      persistWindows(next, `Add ${preset.label} window`);
    }, [markWindowsEdited, persistWindows, replaceWindows],
  );

  const changeWindow = useCallback(
    (id: string, patch: Partial<VibeWindowView>) => {
      markWindowsEdited();
      replaceWindows(windowsRef.current.map((window) => (window.id === id ? { ...window, ...patch } : window)));
    }, [markWindowsEdited, replaceWindows],
  );

  const commitWindow = useCallback(() => {
    markWindowsEdited();
    persistWindows(windowsRef.current, 'Move vibe window');
  }, [markWindowsEdited, persistWindows]);

  const deleteWindow = useCallback((id: string) => {
    markWindowsEdited();
    const next = windowsRef.current.filter((window) => window.id !== id);
    replaceWindows(next);
    persistWindows(next, 'Remove vibe window');
  }, [markWindowsEdited, persistWindows, replaceWindows]);

  const replaceWithTemplate = useCallback((next: VibeWindowView[]) => {
    markWindowsEdited();
    replaceWindows(next);
  }, [markWindowsEdited, replaceWindows]);

  return { windows, addWindow, changeWindow, commitWindow, deleteWindow, replaceWithTemplate };
}
