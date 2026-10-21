import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { api, ApiError } from '@/lib/api';
import type { GuestNowPlaying, GuestRequestInfo, PublicEvent } from '@/lib/api';
import type { RequestStatus } from '@/lib/api/types';
import { useEventStream } from '@/lib/use-event-stream';
import { BACKOFF_INTERVAL_MS, PAGE_SIZE, POLL_INTERVAL_MS } from './join-constants';

export interface GuestRequestStatusUpdate {
  request_id: number;
  status: RequestStatus;
  title?: string;
  artist?: string;
}

interface GuestEventDataState {
  code: string;
  event: PublicEvent | null;
  loading: boolean;
  error: { message: string; status: number } | null;
  guestRequests: GuestRequestInfo[];
  total: number;
  displayLimit: number;
  nowPlaying: GuestNowPlaying | null;
  emailVerified: boolean;
  requestSheetSuggested: boolean;
  pollInterval: number;
}

interface UseGuestEventDataOptions {
  code: string;
  enabled: boolean;
  myRequestIds: Set<number>;
  onMyRequestStatusChanged: (update: GuestRequestStatusUpdate) => void;
}

function emptyGuestEventData(code: string): GuestEventDataState {
  return {
    code,
    event: null,
    loading: true,
    error: null,
    guestRequests: [],
    total: 0,
    displayLimit: PAGE_SIZE,
    nowPlaying: null,
    emailVerified: false,
    requestSheetSuggested: false,
    pollInterval: POLL_INTERVAL_MS,
  };
}

export function useGuestEventData({
  code,
  enabled,
  myRequestIds,
  onMyRequestStatusChanged,
}: UseGuestEventDataOptions) {
  const [storedData, setStoredData] = useState(() => emptyGuestEventData(code));
  const data = storedData.code === code ? storedData : emptyGuestEventData(code);
  const myRequestIdsRef = useRef(myRequestIds);
  const loadRequestsRef = useRef<() => Promise<void>>(async () => {});
  myRequestIdsRef.current = myRequestIds;

  const updateRouteData = useCallback(
    (routeCode: string, update: (current: GuestEventDataState) => GuestEventDataState) => {
      setStoredData((current) => current.code === routeCode ? update(current) : current);
    },
    [],
  );

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    setStoredData(emptyGuestEventData(code));

    void (async () => {
      try {
        const event = await api.getPublicEvent(code);
        if (!active) return;
        updateRouteData(code, (current) => ({ ...current, event, error: null }));

        try {
          const { has_requested: hasRequested } = await api.checkHasRequested(code);
          if (!active) return;
          if (!hasRequested) {
            updateRouteData(code, (current) => ({ ...current, requestSheetSuggested: true }));
          }
        } catch {
          if (active) {
            updateRouteData(code, (current) => ({ ...current, requestSheetSuggested: true }));
          }
        }
      } catch (error) {
        if (!active) return;
        const pageError = error instanceof ApiError
          ? { message: error.message, status: error.status }
          : { message: 'Event not found or has expired.', status: 0 };
        updateRouteData(code, (current) => ({ ...current, error: pageError }));
      } finally {
        if (active) updateRouteData(code, (current) => ({ ...current, loading: false }));
      }
    })();

    return () => { active = false; };
  }, [code, enabled, updateRouteData]);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    api.getCollectProfile(code)
      .then((profile) => {
        if (active) updateRouteData(code, (current) => ({
          ...current,
          emailVerified: profile.email_verified,
        }));
      })
      .catch(() => { /* email verification is best-effort on the live page */ });
    return () => { active = false; };
  }, [code, enabled, updateRouteData]);

  const loadRequests = useCallback(async () => {
    try {
      const response = await api.getPublicRequests(code, { limit: data.displayLimit });
      updateRouteData(code, (current) => ({
        ...current,
        guestRequests: response.requests,
        nowPlaying: response.now_playing,
        total: response.total ?? response.requests.length,
        pollInterval: POLL_INTERVAL_MS,
      }));
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) {
        updateRouteData(code, (current) => ({ ...current, pollInterval: BACKOFF_INTERVAL_MS }));
      }
    }
  }, [code, data.displayLimit, updateRouteData]);
  loadRequestsRef.current = loadRequests;

  useEffect(() => {
    if (!enabled || !data.event) return;
    void loadRequests();
    const interval = setInterval(() => { void loadRequests(); }, data.pollInterval);
    return () => clearInterval(interval);
  }, [data.event, data.pollInterval, enabled, loadRequests]);

  useEventStream(enabled && data.event ? code : null, {
    onRequestCreated: () => { void loadRequestsRef.current(); },
    onRequestStatusChanged: (update) => {
      void loadRequestsRef.current();
      if (myRequestIdsRef.current.has(update.request_id)) onMyRequestStatusChanged(update);
    },
    onNowPlayingChanged: () => { void loadRequestsRef.current(); },
    onRequestsBulkUpdate: () => { void loadRequestsRef.current(); },
  });

  const setEvent: Dispatch<SetStateAction<PublicEvent | null>> = useCallback((action) => {
    updateRouteData(code, (current) => ({
      ...current,
      event: typeof action === 'function' ? action(current.event) : action,
    }));
  }, [code, updateRouteData]);

  const setGuestRequests: Dispatch<SetStateAction<GuestRequestInfo[]>> = useCallback((action) => {
    updateRouteData(code, (current) => ({
      ...current,
      guestRequests: typeof action === 'function' ? action(current.guestRequests) : action,
    }));
  }, [code, updateRouteData]);

  const setDisplayLimit: Dispatch<SetStateAction<number>> = useCallback((action) => {
    updateRouteData(code, (current) => ({
      ...current,
      displayLimit: typeof action === 'function' ? action(current.displayLimit) : action,
    }));
  }, [code, updateRouteData]);

  const setEmailVerified: Dispatch<SetStateAction<boolean>> = useCallback((action) => {
    updateRouteData(code, (current) => ({
      ...current,
      emailVerified: typeof action === 'function' ? action(current.emailVerified) : action,
    }));
  }, [code, updateRouteData]);

  return {
    event: data.event,
    setEvent,
    loading: data.loading,
    error: data.error,
    guestRequests: data.guestRequests,
    setGuestRequests,
    total: data.total,
    displayLimit: data.displayLimit,
    setDisplayLimit,
    nowPlaying: data.nowPlaying,
    emailVerified: data.emailVerified,
    setEmailVerified,
    requestSheetSuggested: data.requestSheetSuggested,
    loadRequests,
  };
}
