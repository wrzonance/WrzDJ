'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { BuildSetResponse } from '@/lib/api/types';
import type { ConfirmAction } from '../components/ConfirmActionDialog';
import type { BuilderCommit } from '../components/useSetDocumentHistory';

interface UseBuilderBuildWorkflowOptions {
  setId: number;
  commit: BuilderCommit;
  onBuildComplete: (result: BuildSetResponse) => void;
  onBuildError: (message: string) => void;
}

export function useBuilderBuildWorkflow({
  setId,
  commit,
  onBuildComplete,
  onBuildError,
}: UseBuilderBuildWorkflowOptions) {
  const [building, setBuilding] = useState(false);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const confirmResolverRef = useRef<((value: boolean) => void) | null>(null);
  const mountedRef = useRef(false);
  const requestIdRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      confirmResolverRef.current?.(false);
      confirmResolverRef.current = null;
    };
  }, [setId]);

  const isCurrentRequest = useCallback(
    (requestId: number) => mountedRef.current && requestIdRef.current === requestId,
    [],
  );

  const requestConfirmation = useCallback((action: ConfirmAction): Promise<boolean> => {
    if (!mountedRef.current) return Promise.resolve(false);
    return new Promise((resolve) => {
      confirmResolverRef.current?.(false);
      confirmResolverRef.current = resolve;
      setConfirmAction(action);
    });
  }, []);

  const closeConfirmation = useCallback((confirmed: boolean) => {
    confirmResolverRef.current?.(confirmed);
    confirmResolverRef.current = null;
    if (mountedRef.current) setConfirmAction(null);
  }, []);

  const runBuild = useCallback(async (requestId: number) => {
    if (!isCurrentRequest(requestId)) return;
    setBuilding(true);
    try {
      const result = await commit('Recompute set order', () => api.buildSet(setId, true));
      if (isCurrentRequest(requestId)) onBuildComplete(result);
    } catch (error) {
      if (isCurrentRequest(requestId)) {
        onBuildError(error instanceof Error ? error.message : 'Failed to recompute set');
      }
    } finally {
      if (isCurrentRequest(requestId)) setBuilding(false);
    }
  }, [commit, isCurrentRequest, onBuildComplete, onBuildError, setId]);

  const requestBuild = useCallback(async (confirmation?: ConfirmAction) => {
    const requestId = ++requestIdRef.current;
    if (confirmation) {
      const confirmed = await requestConfirmation(confirmation);
      if (!confirmed) return;
    }
    if (isCurrentRequest(requestId)) await runBuild(requestId);
  }, [isCurrentRequest, requestConfirmation, runBuild]);

  return {
    building,
    confirmAction,
    requestBuild,
    requestConfirmation,
    closeConfirmation,
  };
}
