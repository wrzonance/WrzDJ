'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';

type JumpSlotRequest = { idx: number; requestId: number };

export function useBuilderPairings(
  setId: number,
  enabled: boolean,
  onWorkspaceRefresh: () => void,
) {
  const [count, setCount] = useState(0);
  const [hasRefreshError, setHasRefreshError] = useState(false);
  const [open, setOpen] = useState(false);
  const [initialPairingId, setInitialPairingId] = useState<number | null>(null);
  const [jumpSlotRequest, setJumpSlotRequest] = useState<JumpSlotRequest | null>(null);
  const requestGeneration = useRef(0);
  const previousSetId = useRef(setId);

  const refresh = useCallback(async () => {
    const generation = ++requestGeneration.current;
    try {
      const state = await api.getPairings(setId);
      if (generation !== requestGeneration.current) return;
      setCount(state.count);
      setHasRefreshError(false);
    } catch {
      if (generation !== requestGeneration.current) return;
      setHasRefreshError(true);
    }
  }, [setId]);

  useEffect(() => {
    if (previousSetId.current !== setId) {
      previousSetId.current = setId;
      setCount(0);
      setHasRefreshError(false);
      setOpen(false);
      setInitialPairingId(null);
      setJumpSlotRequest(null);
    }
    if (enabled) void refresh();
    else requestGeneration.current += 1;
  }, [enabled, refresh, setId]);

  const openPairings = useCallback((pairingId: number | null = null) => {
    setInitialPairingId(pairingId);
    setOpen(true);
    void refresh();
  }, [refresh]);

  const closePairings = useCallback(() => setOpen(false), []);

  const updateCount = useCallback((nextCount?: number) => {
    if (nextCount === undefined) {
      void refresh();
      return;
    }
    // Explicit mutation results are newer than every count request already in flight.
    requestGeneration.current += 1;
    setCount(nextCount);
    setHasRefreshError(false);
  }, [refresh]);

  const handlePairingsChanged = useCallback((nextCount?: number) => {
    updateCount(nextCount);
    onWorkspaceRefresh();
  }, [onWorkspaceRefresh, updateCount]);

  const jumpToSlot = useCallback((idx: number) => {
    setJumpSlotRequest((previous) => ({ idx, requestId: (previous?.requestId ?? 0) + 1 }));
  }, []);

  return {
    count,
    hasRefreshError,
    refresh,
    open,
    initialPairingId,
    jumpSlotRequest,
    openPairings,
    closePairings,
    handlePairingsChanged,
    jumpToSlot,
  };
}
