'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api, KioskDisplay, NowPlayingInfo, PlayHistoryItem, PUBLIC_PAGE_MAX } from '@/lib/api';
import { useEventStream } from '@/lib/use-event-stream';
import { usePollingLoop } from '@/lib/use-polling-loop';

const PUBLIC_PAGE_MAX_INITIAL = 100;

export type KioskDisplayError = { message: string; status: number } | null;

export function useKioskDisplayData(code: string) {
  const [display, setDisplay] = useState<KioskDisplay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<KioskDisplayError>(null);
  const [stagelinqNowPlaying, setStagelinqNowPlaying] = useState<NowPlayingInfo | null>(null);
  const [playHistory, setPlayHistory] = useState<PlayHistoryItem[]>([]);
  const [lastKnownNowPlaying, setLastKnownNowPlaying] = useState<NowPlayingInfo | null>(null);
  const [nowPlayingFading, setNowPlayingFading] = useState(false);

  const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasLoadedRef = useRef(false);
  const [displayLimit, setDisplayLimit] = useState(PUBLIC_PAGE_MAX_INITIAL);
  const displayLimitRef = useRef(displayLimit);
  displayLimitRef.current = displayLimit;
  const loadSeqRef = useRef(0);
  const currentCodeRef = useRef(code);
  currentCodeRef.current = code;
  const mountedCodeRef = useRef(code);

  const loadDisplay = useCallback(async (): Promise<boolean> => {
    const requestedCode = code;
    const seq = ++loadSeqRef.current;
    try {
      const limit = displayLimitRef.current;
      const [kioskData, nowPlayingData, historyData] = await Promise.all([
        api.getKioskDisplay(requestedCode, { limit, offset: 0 }),
        api.getNowPlaying(requestedCode).catch((): undefined => undefined),
        api.getPlayHistory(requestedCode).catch((): undefined => undefined),
      ]);
      // Polls and SSE refreshes can overlap; only the newest response updates the display.
      if (seq !== loadSeqRef.current || currentCodeRef.current !== requestedCode) return true;

      setDisplay(kioskData);
      if (
        kioskData.accepted_queue_total > kioskData.accepted_queue.length &&
        displayLimitRef.current < PUBLIC_PAGE_MAX
      ) {
        setDisplayLimit(Math.min(limit + PUBLIC_PAGE_MAX_INITIAL, PUBLIC_PAGE_MAX));
      }
      // Preserve previous bridge data when a subrequest fails transiently.
      if (nowPlayingData !== undefined) setStagelinqNowPlaying(nowPlayingData);
      if (historyData !== undefined) setPlayHistory(historyData.items);
      setError(null);
      hasLoadedRef.current = true;
      return true;
    } catch (err) {
      // A superseded request must not publish an error or stop the polling loop.
      if (seq !== loadSeqRef.current || currentCodeRef.current !== requestedCode) return true;
      if (err instanceof ApiError && (err.status === 404 || err.status === 410)) {
        setError({ message: err.message, status: err.status });
        return false;
      }
      if (!hasLoadedRef.current) {
        setError({ message: 'Event not found or expired', status: 0 });
      }
      return true;
    } finally {
      if (seq === loadSeqRef.current && currentCodeRef.current === requestedCode) {
        setLoading(false);
      }
    }
  }, [code]);

  usePollingLoop(true, loadDisplay, 10_000);

  const loadDisplayRef = useRef(loadDisplay);
  loadDisplayRef.current = loadDisplay;
  useEventStream(code, {
    onRequestCreated: () => { void loadDisplayRef.current(); },
    onRequestStatusChanged: () => { void loadDisplayRef.current(); },
    onNowPlayingChanged: () => { void loadDisplayRef.current(); },
    onRequestsBulkUpdate: () => { void loadDisplayRef.current(); },
    onBridgeStatusChanged: () => { void loadDisplayRef.current(); },
  });

  useEffect(() => {
    if (mountedCodeRef.current === code) return;
    mountedCodeRef.current = code;
    loadSeqRef.current += 1;
    hasLoadedRef.current = false;
    setDisplay(null);
    setLoading(true);
    setError(null);
    setStagelinqNowPlaying(null);
    setPlayHistory([]);
    setLastKnownNowPlaying(null);
    setNowPlayingFading(false);
    if (staleTimerRef.current) {
      clearTimeout(staleTimerRef.current);
      staleTimerRef.current = null;
    }
    void loadDisplay();
  }, [code, loadDisplay]);

  useEffect(() => {
    if (stagelinqNowPlaying) {
      if (staleTimerRef.current) {
        clearTimeout(staleTimerRef.current);
        staleTimerRef.current = null;
      }
      setLastKnownNowPlaying(stagelinqNowPlaying);
      setNowPlayingFading(false);
    } else if (lastKnownNowPlaying && !staleTimerRef.current) {
      setNowPlayingFading(true);
      staleTimerRef.current = setTimeout(() => {
        staleTimerRef.current = null;
        setLastKnownNowPlaying(null);
        setNowPlayingFading(false);
      }, 10_000);
    }
  }, [stagelinqNowPlaying, lastKnownNowPlaying]);

  useEffect(() => () => {
    loadSeqRef.current += 1;
    if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
  }, []);

  return {
    display,
    loading,
    error,
    stagelinqNowPlaying,
    playHistory,
    lastKnownNowPlaying,
    nowPlayingFading,
    loadDisplay,
  };
}
