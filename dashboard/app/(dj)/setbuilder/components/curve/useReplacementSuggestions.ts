import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { REPLACE_PROMPT_THRESHOLD, rankReplacementCandidates } from './curveMath';
import type { ReplacePrompt } from '../pool/ReplacePopover';
import type { SlotView, TrackView } from '../types';
import type { BuilderCommit } from '../useSetDocumentHistory';
import { replaceSlotTrackInDocument } from '../documentMath';

const SUGGEST_KEY = 'wrzdj.curve.suggestReplacements';

function readSuggestSetting(): boolean | null {
  try {
    const stored = window.localStorage.getItem(SUGGEST_KEY);
    return stored == null ? null : stored !== 'false';
  } catch {
    return null;
  }
}

function writeSuggestSetting(on: boolean): void {
  try {
    window.localStorage.setItem(SUGGEST_KEY, String(on));
  } catch {
    // Preference persistence is best effort.
  }
}

interface ReplacementSuggestionsOptions {
  setId: number;
  slots: SlotView[];
  pool: TrackView[];
  onSlotsChange: (updater: (previous: SlotView[]) => SlotView[]) => void;
  commit?: BuilderCommit;
  setting?: boolean;
  onSettingChange?: (enabled: boolean) => void;
}

export function useReplacementSuggestions({
  setId,
  slots,
  pool,
  onSlotsChange,
  commit,
  setting,
  onSettingChange,
}: ReplacementSuggestionsOptions) {
  const activeScope = useRef({ setId, generation: 0 });
  const mounted = useRef(true);
  const [prompt, setPrompt] = useState<ReplacePrompt | null>(null);
  const [replacementError, setReplacementError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);

  useLayoutEffect(() => {
    if (activeScope.current.setId !== setId) {
      activeScope.current = {
        setId,
        generation: activeScope.current.generation + 1,
      };
    }
  }, [setId]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    setPrompt(null);
    setReplacementError(null);
  }, [setId]);

  useEffect(() => {
    if (setting != null) {
      setEnabled(setting);
      return;
    }
    const stored = readSuggestSetting();
    if (stored != null) setEnabled(stored);
  }, [setting]);

  const setSuggestReplacements = (next: boolean) => {
    setEnabled(next);
    writeSuggestSetting(next);
    onSettingChange?.(next);
  };

  const handleTargetDragEnd = (
    idx: number,
    energy: number,
    anchor: { x: number; y: number },
  ) => {
    setReplacementError(null);
    const slot = slots[idx];
    if (!slot) return;
    if (slot.locked) {
      setPrompt(null);
      return;
    }
    onSlotsChange((previous) =>
      previous.map((item, index) => (index === idx ? { ...item, targetEnergy: energy } : item)),
    );
    const save = () => api.updateSlotTarget(setId, slot.id, energy);
    const run = commit ? commit(`Retarget slot ${idx + 1}`, save) : save();
    run.catch(() => {
      // The optimistic target is refreshed on the next load.
    });
    if (enabled && Math.abs(energy - slot.track.energy) >= REPLACE_PROMPT_THRESHOLD) {
      setPrompt({ slotIdx: idx, targetEnergy: energy, anchorX: anchor.x, anchorY: anchor.y });
    } else {
      setPrompt(null);
    }
  };

  const promptSlot = prompt ? slots[prompt.slotIdx] : null;
  const candidates = useMemo(() => {
    if (!prompt || !promptSlot) return [];
    const inSetIds = new Set(slots.map((slot) => slot.track.id));
    return rankReplacementCandidates(
      prompt.targetEnergy,
      prompt.slotIdx > 0 ? slots[prompt.slotIdx - 1].track : null,
      pool,
      inSetIds,
    );
  }, [pool, prompt, promptSlot, slots]);

  const handleReplace = (slotId: number, trackId: string) => {
    const candidate = pool.find((track) => track.id === trackId);
    if (!candidate) return;
    setReplacementError(null);
    const requestSetId = setId;
    const requestGeneration = activeScope.current.generation;
    const save = async () => {
      const snapshot = await api.getSetDocument(requestSetId);
      const poolTrack = snapshot.pool.tracks.find(
        (track) => (track.track_id ?? `pool-${track.id}`) === candidate.id,
      );
      if (!poolTrack) throw new Error('Replacement track is no longer in the pool');
      return api.putSetDocument(
        requestSetId,
        replaceSlotTrackInDocument(snapshot, slotId, poolTrack.id),
      );
    };
    const run = commit ? commit('Replace set slot track', save) : save();
    run
      .then(() => {
        if (
          !mounted.current ||
          activeScope.current.setId !== requestSetId ||
          activeScope.current.generation !== requestGeneration
        ) return;
        onSlotsChange((previous) =>
          previous.map((slot) => (slot.id === slotId ? { ...slot, track: candidate } : slot)),
        );
        setPrompt(null);
      })
      .catch(() => {
        if (
          mounted.current &&
          activeScope.current.setId === requestSetId &&
          activeScope.current.generation === requestGeneration
        ) {
          setReplacementError('Could not replace this track. Please try again.');
        }
      });
  };

  const dismissPrompt = () => {
    setPrompt(null);
    setReplacementError(null);
  };

  return {
    enabled,
    setSuggestReplacements,
    prompt,
    promptSlot,
    candidates,
    replacementError,
    handleTargetDragEnd,
    handleReplace,
    dismissPrompt,
  };
}
