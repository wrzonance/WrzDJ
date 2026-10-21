import { useEffect, useRef, useState, useCallback } from 'react';
import { getApiUrl } from './api/shared';
import type { RequestStatus } from './api/types';

interface EventStreamHandlers {
  onRequestCreated?: (data: { request_id: number; title: string; artist: string }) => void;
  onRequestStatusChanged?: (data: { request_id: number; status: RequestStatus; title?: string; artist?: string }) => void;
  onNowPlayingChanged?: (data: { title: string; artist: string; source: string }) => void;
  onRequestsBulkUpdate?: (data: { action: string; count: number }) => void;
  onBridgeStatusChanged?: (data: {
    connected: boolean;
    device_name: string | null;
    circuit_breaker_state?: string | null;
    buffer_size?: number | null;
    plugin_id?: string | null;
    deck_count?: number | null;
    uptime_seconds?: number | null;
  }) => void;
}

const INITIAL_RETRY_MS = 1000;
const MAX_RETRY_MS = 30_000;
const REQUEST_STATUSES = {
  new: true,
  accepted: true,
  playing: true,
  played: true,
  rejected: true,
} satisfies Record<RequestStatus, true>;

type EventDataValidator<T> = (value: unknown) => value is T;

function parseEventData<T>(raw: string, isValid: EventDataValidator<T>): T | null {
  try {
    const value: unknown = JSON.parse(raw);
    return isValid(value) ? value : null;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isNonEmptyString(value: unknown): value is string {
  return isString(value) && value.length > 0;
}

function isRequestCreated(value: unknown): value is Parameters<
  NonNullable<EventStreamHandlers['onRequestCreated']>
>[0] {
  return (
    isRecord(value) &&
    Number.isSafeInteger(value.request_id) &&
    isString(value.title) &&
    isString(value.artist)
  );
}

function isRequestStatusChanged(value: unknown): value is Parameters<
  NonNullable<EventStreamHandlers['onRequestStatusChanged']>
>[0] {
  if (!isRecord(value)) return false;
  if (!Number.isSafeInteger(value.request_id)) return false;
  if (
    typeof value.status !== 'string' ||
    !Object.hasOwn(REQUEST_STATUSES, value.status)
  ) {
    return false;
  }
  return (
    (value.title === undefined || isString(value.title)) &&
    (value.artist === undefined || isString(value.artist))
  );
}

function isNowPlayingChanged(value: unknown): value is Parameters<
  NonNullable<EventStreamHandlers['onNowPlayingChanged']>
>[0] {
  return (
    isRecord(value) &&
    isString(value.title) &&
    isString(value.artist) &&
    isNonEmptyString(value.source)
  );
}

function isRequestsBulkUpdate(value: unknown): value is Parameters<
  NonNullable<EventStreamHandlers['onRequestsBulkUpdate']>
>[0] {
  return (
    isRecord(value) &&
    typeof value.action === 'string' &&
    ['accepted', 'rejected', 'deleted'].includes(value.action) &&
    Number.isSafeInteger(value.count) &&
    Number(value.count) >= 0
  );
}

function isOptionalNullableString(value: unknown): boolean {
  return value === undefined || value === null || isString(value);
}

function isOptionalNonNegativeInteger(value: unknown): boolean {
  return value === undefined || value === null || (Number.isSafeInteger(value) && Number(value) >= 0);
}

function isBridgeStatusChanged(value: unknown): value is Parameters<
  NonNullable<EventStreamHandlers['onBridgeStatusChanged']>
>[0] {
  if (!isRecord(value) || typeof value.connected !== 'boolean') return false;
  if (value.device_name !== null && !isString(value.device_name)) return false;
  if (!isOptionalNullableString(value.circuit_breaker_state)) return false;
  if (!isOptionalNonNegativeInteger(value.buffer_size)) return false;
  if (!isOptionalNullableString(value.plugin_id)) return false;
  if (!isOptionalNonNegativeInteger(value.deck_count)) return false;
  return isOptionalNonNegativeInteger(value.uptime_seconds);
}

export function useEventStream(
  eventCode: string | null,
  handlers: EventStreamHandlers,
): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const retryCount = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handlersRef = useRef(handlers);
  const eventCodeRef = useRef(eventCode);
  const lifecycleRef = useRef(0);
  handlersRef.current = handlers;
  eventCodeRef.current = eventCode;

  const connect = useCallback((lifecycle: number) => {
    if (!eventCode || eventCodeRef.current !== eventCode || lifecycleRef.current !== lifecycle) return;
    if (typeof EventSource === 'undefined') return;

    const url = `${getApiUrl()}/api/public/events/${eventCode}/stream`;
    const es = new EventSource(url);
    eventSourceRef.current = es;
    const isCurrentSource = () =>
      eventCodeRef.current === eventCode &&
      lifecycleRef.current === lifecycle &&
      eventSourceRef.current === es;

    es.onopen = () => {
      if (!isCurrentSource()) return;
      setConnected(true);
      retryCount.current = 0;
    };

    es.onerror = () => {
      if (!isCurrentSource()) return;
      es.close();
      eventSourceRef.current = null;
      setConnected(false);

      // Exponential backoff capped at MAX_RETRY_MS, retries indefinitely
      const delay = Math.min(
        INITIAL_RETRY_MS * Math.pow(2, retryCount.current),
        MAX_RETRY_MS,
      );
      retryCount.current++;
      retryTimerRef.current = setTimeout(() => {
        retryTimerRef.current = null;
        connect(lifecycle);
      }, delay);
    };

    es.addEventListener('request_created', (e) => {
      if (!isCurrentSource()) return;
      const data = parseEventData(e.data, isRequestCreated);
      if (data) handlersRef.current.onRequestCreated?.(data);
    });
    es.addEventListener('request_status_changed', (e) => {
      if (!isCurrentSource()) return;
      const data = parseEventData(e.data, isRequestStatusChanged);
      if (data) handlersRef.current.onRequestStatusChanged?.(data);
    });
    es.addEventListener('now_playing_changed', (e) => {
      if (!isCurrentSource()) return;
      const data = parseEventData(e.data, isNowPlayingChanged);
      if (data) handlersRef.current.onNowPlayingChanged?.(data);
    });
    es.addEventListener('requests_bulk_update', (e) => {
      if (!isCurrentSource()) return;
      const data = parseEventData(e.data, isRequestsBulkUpdate);
      if (data) handlersRef.current.onRequestsBulkUpdate?.(data);
    });
    es.addEventListener('bridge_status_changed', (e) => {
      if (!isCurrentSource()) return;
      const data = parseEventData(e.data, isBridgeStatusChanged);
      if (data) handlersRef.current.onBridgeStatusChanged?.(data);
    });
  }, [eventCode]);

  useEffect(() => {
    const lifecycle = lifecycleRef.current + 1;
    lifecycleRef.current = lifecycle;
    retryCount.current = 0;
    connect(lifecycle);
    return () => {
      lifecycleRef.current++;
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      const source = eventSourceRef.current;
      eventSourceRef.current = null;
      source?.close();
      setConnected(false);
    };
  }, [connect]);

  return { connected };
}
