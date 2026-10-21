'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { NowPlayingInfo, PlayHistoryItem, PublicBridgeStatus } from '@/lib/api';

interface UseEventLiveStatusOptions {
  routeCode: string;
  joinCode: string | null;
}

interface BridgeDetails {
  circuitBreakerState: string | null;
  bufferSize: number | null;
  pluginId: string | null;
  deckCount: number | null;
  uptimeSeconds: number | null;
}

interface LiveStatusState {
  key: string;
  playHistory: PlayHistoryItem[];
  playHistoryTotal: number;
  nowPlaying: NowPlayingInfo | null;
  bridgeConnected: boolean;
  bridgeDetails: BridgeDetails | null;
}

type BridgeStatusUpdate = Pick<PublicBridgeStatus, 'connected'> & Partial<BridgeDetailsAsApi>;
type BridgeDetailsAsApi = Pick<PublicBridgeStatus,
  'circuit_breaker_state' | 'buffer_size' | 'plugin_id' | 'deck_count' | 'uptime_seconds'
>;

const DISCONNECTED_BRIDGE: PublicBridgeStatus = {
  connected: false,
  device_name: null,
  last_seen: null,
  circuit_breaker_state: null,
  buffer_size: null,
  plugin_id: null,
  deck_count: null,
  uptime_seconds: null,
};

function routeKey(routeCode: string, joinCode: string | null) {
  return `${routeCode}\u0000${joinCode ?? ''}`;
}

function emptyState(key: string): LiveStatusState {
  return {
    key,
    playHistory: [],
    playHistoryTotal: 0,
    nowPlaying: null,
    bridgeConnected: false,
    bridgeDetails: null,
  };
}

function toBridgeDetails(status: Partial<BridgeDetailsAsApi>): BridgeDetails {
  return {
    circuitBreakerState: status.circuit_breaker_state ?? null,
    bufferSize: status.buffer_size ?? null,
    pluginId: status.plugin_id ?? null,
    deckCount: status.deck_count ?? null,
    uptimeSeconds: status.uptime_seconds ?? null,
  };
}

export function useEventLiveStatus({ routeCode, joinCode }: UseEventLiveStatusOptions) {
  const target = { routeCode, joinCode, key: routeKey(routeCode, joinCode) };
  const currentTarget = useRef(target);
  currentTarget.current = target;
  const requestSequence = useRef(0);
  const bridgeRevision = useRef(0);
  const [state, setState] = useState(() => emptyState(target.key));

  const refresh = useCallback(async () => {
    const requestedTarget = currentTarget.current;
    if (!requestedTarget.joinCode) return;
    const requestId = ++requestSequence.current;
    const requestedBridgeRevision = bridgeRevision.current;

    const [history, nowPlaying, bridgeStatus] = await Promise.all([
      api.getPlayHistory(requestedTarget.joinCode).catch(() => undefined),
      api.getNowPlaying(requestedTarget.joinCode).catch((): undefined => undefined),
      api.getBridgeStatus(requestedTarget.joinCode).catch(() => DISCONNECTED_BRIDGE),
    ]);

    if (
      requestId !== requestSequence.current
      || currentTarget.current.key !== requestedTarget.key
    ) return;

    setState((current) => {
      const previous = current.key === requestedTarget.key ? current : emptyState(requestedTarget.key);
      return {
        ...previous,
        ...(history === undefined ? {} : {
          playHistory: history.items,
          playHistoryTotal: history.total,
        }),
        ...(nowPlaying === undefined ? {} : { nowPlaying }),
        ...(bridgeRevision.current === requestedBridgeRevision ? {
          bridgeConnected: bridgeStatus.connected,
          bridgeDetails: toBridgeDetails(bridgeStatus),
        } : {}),
      };
    });
  }, []);

  useEffect(() => {
    requestSequence.current += 1;
    setState(emptyState(target.key));
    if (joinCode) void refresh();
    return () => {
      requestSequence.current += 1;
    };
  }, [target.key, joinCode, refresh]);

  const applyBridgeStatus = useCallback((status: BridgeStatusUpdate, expectedRouteCode: string) => {
    const current = currentTarget.current;
    if (current.routeCode !== expectedRouteCode) return;
    bridgeRevision.current += 1;
    setState((stateNow) => {
      if (stateNow.key !== current.key) return stateNow;
      return {
        ...stateNow,
        bridgeConnected: status.connected,
        bridgeDetails: toBridgeDetails(status),
      };
    });
  }, []);

  const currentState = state.key === target.key ? state : emptyState(target.key);
  return { ...currentState, refresh, applyBridgeStatus };
}
