'use client';

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { SetDetail } from '@/lib/api/types';
import {
  DEFAULT_AVG_TRANSITION_OVERLAP_SEC,
  type TargetProjection,
  type TargetSettings,
} from '../components/curve/targetMath';

const DEFAULT_TARGET_SETTINGS: TargetSettings = {
  targetDurationSec: null,
  avgTransitionOverlapSec: DEFAULT_AVG_TRANSITION_OVERLAP_SEC,
};

function settingsFromSet(set: SetDetail): TargetSettings {
  return {
    targetDurationSec: set.target_duration_sec,
    avgTransitionOverlapSec:
      set.avg_transition_overlap_sec ?? DEFAULT_AVG_TRANSITION_OVERLAP_SEC,
  };
}

export function useSetTargetSettings(
  set: SetDetail | null,
  onSetUpdated: (updated: SetDetail) => void,
  onSaveError: (message: string) => void,
) {
  const [settings, setSettings] = useState<TargetSettings>(DEFAULT_TARGET_SETTINGS);
  const [projection, setProjection] = useState<TargetProjection | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (set) setSettings(settingsFromSet(set));
  }, [set?.id, set?.target_duration_sec, set?.avg_transition_overlap_sec]);

  const dirty = Boolean(
    set &&
      (settings.targetDurationSec !== set.target_duration_sec ||
        settings.avgTransitionOverlapSec !==
          (set.avg_transition_overlap_sec ?? DEFAULT_AVG_TRANSITION_OVERLAP_SEC)),
  );

  const update = useCallback((nextSettings: TargetSettings) => {
    setError(null);
    setSettings(nextSettings);
  }, []);

  const undo = useCallback(() => {
    if (!set) return;
    setError(null);
    setSettings(settingsFromSet(set));
  }, [set]);

  const save = useCallback(async () => {
    if (!set || !dirty) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateSetTargetSettings(
        set.id,
        settings.targetDurationSec,
        settings.avgTransitionOverlapSec,
      );
      onSetUpdated(updated);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save target settings';
      setError(message);
      onSaveError(message);
    } finally {
      setSaving(false);
    }
  }, [dirty, onSaveError, onSetUpdated, set, settings]);

  const updateProjection = useCallback((nextProjection: TargetProjection) => {
    setProjection(nextProjection);
  }, []);

  return { settings, projection, dirty, saving, error, update, undo, save, updateProjection };
}
