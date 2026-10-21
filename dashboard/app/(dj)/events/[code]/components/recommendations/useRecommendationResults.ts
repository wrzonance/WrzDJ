import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import type {
  EventMusicProfile,
  LLMQueryInfo,
  RecommendedTrack,
  RecommendationResponse,
} from '@/lib/api/types';

export type RecommendationMode = 'requests' | 'template' | 'llm';
export type GenerateState = 'idle' | 'working' | 'complete';

interface ModeResultCache {
  suggestions: RecommendedTrack[];
  profile: EventMusicProfile | null;
  llmQueries: LLMQueryInfo[];
  llmModel: string;
  scrollTop: number;
}

interface ResultStore {
  eventKey: string;
  modes: Record<RecommendationMode, ModeResultCache>;
}

interface ResultScope {
  eventKey: string;
  eventVersion: number;
  mode: RecommendationMode;
}

interface PendingAction {
  kind: 'single' | 'all';
  trackKey: string | null;
}

interface GenerateOptions {
  prompt: string;
  selectedPlaylist: string | null;
}

const emptyModeResults = (): ModeResultCache => ({
  suggestions: [],
  profile: null,
  llmQueries: [],
  llmModel: '',
  scrollTop: 0,
});

const emptyResultStore = (eventKey: string): ResultStore => ({
  eventKey,
  modes: {
    requests: emptyModeResults(),
    template: emptyModeResults(),
    llm: emptyModeResults(),
  },
});

const trackKey = (track: RecommendedTrack) => `${track.artist}-${track.title}`;
const errorMessage = (error: unknown, fallback: string) =>
  error instanceof ApiError ? error.message : fallback;

export function useRecommendationResults(
  code: string,
  onAcceptTrack: (track: RecommendedTrack) => Promise<void>,
) {
  const [selection, setSelection] = useState<{ eventKey: string; mode: RecommendationMode }>({
    eventKey: code,
    mode: 'requests',
  });
  const mode = selection.eventKey === code ? selection.mode : 'requests';
  const [error, setError] = useState<string | null>(null);
  const [generateState, setGenerateState] = useState<GenerateState>('idle');
  const [llmAvailable, setLlmAvailable] = useState(false);
  const [, setRevision] = useState(0);
  const [, setActionRevision] = useState(0);

  const eventKeyRef = useRef(code);
  const eventVersionRef = useRef(0);
  const modeRef = useRef(mode);
  const onAcceptTrackRef = useRef(onAcceptTrack);
  const resultStoreRef = useRef(emptyResultStore(code));
  const generationLocksRef = useRef(new Set<string>());
  const pendingActionsRef = useRef(new Map<string, PendingAction>());
  const mountedRef = useRef(false);
  const completionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  onAcceptTrackRef.current = onAcceptTrack;
  modeRef.current = mode;
  if (eventKeyRef.current !== code) {
    eventKeyRef.current = code;
    eventVersionRef.current += 1;
    resultStoreRef.current = emptyResultStore(code);
  }
  if (resultStoreRef.current.eventKey !== code) {
    resultStoreRef.current = emptyResultStore(code);
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (completionTimerRef.current) clearTimeout(completionTimerRef.current);
    };
  }, []);

  useEffect(() => {
    setSelection({ eventKey: code, mode: 'requests' });
    setError(null);
    setGenerateState('idle');
    setLlmAvailable(false);
    if (completionTimerRef.current) {
      clearTimeout(completionTimerRef.current);
      completionTimerRef.current = null;
    }
  }, [code]);

  const captureScope = useCallback((): ResultScope => ({
    eventKey: eventKeyRef.current,
    eventVersion: eventVersionRef.current,
    mode: modeRef.current,
  }), []);

  const isCurrentEvent = useCallback((scope: ResultScope) =>
    mountedRef.current && scope.eventKey === eventKeyRef.current
      && scope.eventVersion === eventVersionRef.current, []);

  const isVisibleScope = useCallback((scope: ResultScope) =>
    isCurrentEvent(scope) && scope.mode === modeRef.current, [isCurrentEvent]);

  const refresh = useCallback(() => {
    if (mountedRef.current) setRevision((revision) => revision + 1);
  }, []);

  const updateModeResults = useCallback((
    scope: ResultScope,
    updates: Partial<ModeResultCache>,
  ) => {
    if (!isCurrentEvent(scope)) return;
    const previous = resultStoreRef.current.modes[scope.mode];
    resultStoreRef.current.modes[scope.mode] = { ...previous, ...updates };
    if (isVisibleScope(scope)) refresh();
  }, [isCurrentEvent, isVisibleScope, refresh]);

  const removeAcceptedTrack = useCallback((scope: ResultScope, acceptedKey: string) => {
    if (!isCurrentEvent(scope)) return;
    const previous = resultStoreRef.current.modes[scope.mode];
    resultStoreRef.current.modes[scope.mode] = {
      ...previous,
      suggestions: previous.suggestions.filter((track) => trackKey(track) !== acceptedKey),
    };
    if (isVisibleScope(scope)) refresh();
  }, [isCurrentEvent, isVisibleScope, refresh]);

  const pendingKey = (scope: ResultScope) => `${scope.eventVersion}:${scope.mode}`;
  const currentPending = pendingActionsRef.current.get(`${eventVersionRef.current}:${mode}`);
  const generate = useCallback(async ({ prompt, selectedPlaylist }: GenerateOptions) => {
    const scope = captureScope();
    const lockKey = `${scope.eventVersion}:${scope.eventKey}`;
    if (generationLocksRef.current.has(lockKey)) return;
    generationLocksRef.current.add(lockKey);
    refresh();
    if (completionTimerRef.current) {
      clearTimeout(completionTimerRef.current);
      completionTimerRef.current = null;
    }
    setGenerateState('working');
    setError(null);
    updateModeResults(scope, { llmQueries: [] });
    try {
      if (scope.mode === 'llm') {
        const result = await api.generateLLMRecommendations(scope.eventKey, prompt);
        if (!isCurrentEvent(scope)) return;
        updateModeResults(scope, {
          suggestions: result.suggestions,
          profile: result.profile,
          llmQueries: result.llm_queries,
          llmModel: result.llm_model,
        });
      } else {
        let result: RecommendationResponse;
        if (scope.mode === 'template' && selectedPlaylist) {
          const [source, playlistId] = selectedPlaylist.split(':');
          result = await api.generateRecommendationsFromTemplate(
            scope.eventKey,
            source,
            playlistId,
          );
        } else {
          result = await api.generateRecommendations(scope.eventKey);
        }
        if (!isCurrentEvent(scope)) return;
        updateModeResults(scope, {
          suggestions: result.suggestions,
          profile: result.profile,
          llmQueries: [],
        });
        setLlmAvailable(result.llm_available);
      }
      if (isVisibleScope(scope)) {
        setGenerateState('complete');
        completionTimerRef.current = setTimeout(() => {
          if (isVisibleScope(scope)) setGenerateState('idle');
        }, 2000);
      }
    } catch (err) {
      if (isVisibleScope(scope)) {
        setError(errorMessage(err, 'Failed to generate suggestions'));
        setGenerateState('idle');
      }
    } finally {
      generationLocksRef.current.delete(lockKey);
      refresh();
    }
  }, [captureScope, isCurrentEvent, isVisibleScope, refresh, updateModeResults]);

  const acceptTrack = useCallback(async (track: RecommendedTrack) => {
    const scope = captureScope();
    const key = pendingKey(scope);
    if (pendingActionsRef.current.has(key)) return;
    pendingActionsRef.current.set(key, { kind: 'single', trackKey: trackKey(track) });
    if (mountedRef.current) setActionRevision((revision) => revision + 1);
    const accept = onAcceptTrackRef.current;
    try {
      await accept(track);
      removeAcceptedTrack(scope, trackKey(track));
    } catch (err) {
      if (isVisibleScope(scope)) setError(errorMessage(err, 'Failed to accept track'));
    } finally {
      pendingActionsRef.current.delete(key);
      if (mountedRef.current) setActionRevision((revision) => revision + 1);
    }
  }, [captureScope, isVisibleScope, removeAcceptedTrack]);

  const acceptAll = useCallback(async () => {
    const scope = captureScope();
    const key = pendingKey(scope);
    if (pendingActionsRef.current.has(key)) return;
    const tracks = [...resultStoreRef.current.modes[scope.mode].suggestions];
    if (tracks.length === 0) return;
    pendingActionsRef.current.set(key, { kind: 'all', trackKey: null });
    if (mountedRef.current) setActionRevision((revision) => revision + 1);
    const accept = onAcceptTrackRef.current;
    try {
      for (const track of tracks) {
        await accept(track);
        removeAcceptedTrack(scope, trackKey(track));
      }
    } catch (err) {
      if (isVisibleScope(scope)) setError(errorMessage(err, 'Failed to accept all tracks'));
    } finally {
      pendingActionsRef.current.delete(key);
      if (mountedRef.current) setActionRevision((revision) => revision + 1);
    }
  }, [captureScope, isVisibleScope, removeAcceptedTrack]);

  const clearCurrentMode = useCallback(() => {
    resultStoreRef.current.modes[modeRef.current] = emptyModeResults();
    setError(null);
    refresh();
  }, [refresh]);

  const changeMode = useCallback((nextMode: RecommendationMode, scrollTop: number): number | null => {
    const currentMode = modeRef.current;
    if (nextMode === currentMode) return null;
    resultStoreRef.current.modes[currentMode] = {
      ...resultStoreRef.current.modes[currentMode],
      scrollTop,
    };
    modeRef.current = nextMode;
    const nextScrollTop = resultStoreRef.current.modes[nextMode].scrollTop;
    setSelection({ eventKey: eventKeyRef.current, mode: nextMode });
    setError(null);
    setGenerateState('idle');
    if (completionTimerRef.current) {
      clearTimeout(completionTimerRef.current);
      completionTimerRef.current = null;
    }
    return nextScrollTop;
  }, []);

  const store = resultStoreRef.current;
  const activeResults = store.modes[mode];
  const loading = generationLocksRef.current.has(`${eventVersionRef.current}:${code}`);
  const visiblePending = currentPending ?? null;

  return {
    mode,
    suggestions: activeResults.suggestions,
    profile: activeResults.profile,
    llmQueries: activeResults.llmQueries,
    llmModel: activeResults.llmModel,
    scrollTop: activeResults.scrollTop,
    loading,
    error,
    setError,
    llmAvailable,
    generateState,
    acceptingId: visiblePending?.kind === 'single' ? visiblePending.trackKey : null,
    acceptingAll: visiblePending?.kind === 'all',
    hasPendingAcceptance: !!visiblePending,
    generate,
    acceptTrack,
    acceptAll,
    clearCurrentMode,
    changeMode,
  };
}
