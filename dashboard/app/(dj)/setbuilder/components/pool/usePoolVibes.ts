'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import type { PoolVibeOverrideIn, TrackVibeState } from '@/lib/api/types';

function buildVibeMap(tracks: TrackVibeState[]) {
  return new Map(tracks.map((vibe) => [vibe.pool_track_id, vibe]));
}

export function usePoolVibes(setId: number, setToast: (message: string | null) => void) {
  const [vibes, setVibes] = useState<Map<number, TrackVibeState>>(new Map());
  const [showVibes, setShowVibes] = useState(false);
  const [vibesLoaded, setVibesLoaded] = useState(false);
  const [vibesBusy, setVibesBusy] = useState(false);
  const [vibeWriteBusyIds, setVibeWriteBusyIds] = useState<Set<number>>(new Set());
  const requestGenerationRef = useRef(0);

  useEffect(() => {
    requestGenerationRef.current += 1;
    setVibes(new Map());
    setShowVibes(false);
    setVibesLoaded(false);
    setVibesBusy(false);
    setVibeWriteBusyIds(new Set());
  }, [setId]);

  const toggleVibes = useCallback(() => {
    if (!showVibes && !vibesLoaded && !vibesBusy) {
      const generation = requestGenerationRef.current;
      setVibesBusy(true);
      api.getPoolVibes(setId)
        .then((result) => {
          if (generation !== requestGenerationRef.current) return;
          setVibes(buildVibeMap(result.tracks));
          setVibesLoaded(true);
        })
        .catch(() => {
          if (generation === requestGenerationRef.current) setToast('Failed to load vibes');
        })
        .finally(() => {
          if (generation === requestGenerationRef.current) setVibesBusy(false);
        });
    }
    setShowVibes((visible) => !visible);
  }, [showVibes, vibesLoaded, vibesBusy, setId, setToast]);

  const analyzeVibes = useCallback(async () => {
    const generation = requestGenerationRef.current;
    setVibesBusy(true);
    try {
      const result = await api.enrichPoolVibes(setId);
      if (generation !== requestGenerationRef.current) return;
      setVibes(buildVibeMap(result.vibes.tracks));
      setToast(result.enriched + ' analyzed · ' + result.cached + ' cached · ' + result.failed + ' failed');
    } catch (err) {
      if (generation !== requestGenerationRef.current) return;
      setToast(err instanceof ApiError && err.status === 400 ? err.message : 'Vibe analysis failed');
    } finally {
      if (generation === requestGenerationRef.current) setVibesBusy(false);
    }
  }, [setId, setToast]);

  const updateVibe = useCallback(async (
    poolTrackId: number,
    action: () => Promise<{ tracks: TrackVibeState[] }>,
    success: string,
    fallback: string,
  ) => {
    const generation = requestGenerationRef.current;
    setVibeWriteBusyIds((prev) => new Set(prev).add(poolTrackId));
    try {
      const result = await action();
      if (generation !== requestGenerationRef.current) return false;
      setVibes(buildVibeMap(result.tracks));
      setVibesLoaded(true);
      setToast(success);
      return true;
    } catch (err) {
      if (generation !== requestGenerationRef.current) return false;
      setToast(err instanceof ApiError ? err.message : fallback);
      return false;
    } finally {
      if (generation === requestGenerationRef.current) {
        setVibeWriteBusyIds((prev) => {
          const next = new Set(prev);
          next.delete(poolTrackId);
          return next;
        });
      }
    }
  }, [setToast]);

  const agreeVibe = useCallback((id: number) =>
    updateVibe(id, () => api.agreePoolVibe(setId, id), 'Vibe upvoted', 'Vibe upvote failed'), [setId, updateVibe]);

  const saveVibeOverride = useCallback((id: number, payload: PoolVibeOverrideIn) =>
    updateVibe(id, () => api.overridePoolVibe(setId, id, payload), 'Vibe override saved', 'Vibe override failed'), [setId, updateVibe]);

  return { vibes, showVibes, vibesBusy, vibeWriteBusyIds, toggleVibes, analyzeVibes, agreeVibe, saveVibeOverride };
}
