/**
 * TypeScript interfaces for bridge data structures.
 */

/** Payload sent to POST /api/bridge/nowplaying */
export interface NowPlayingPayload {
  event_code: string;
  title: string;
  artist: string;
  album?: string | null;
  deck?: string | null;
  /** Plugin ID (e.g., "stagelinq", "pioneer", "serato", "traktor") */
  source?: string | null;
  /** True when this track is being replayed from the buffer after backend recovery */
  delayed?: boolean;
  /** For a delayed track: how long ago it was buffered (ms), so the server can order the history */
  played_ago_ms?: number;
}

/** Payload sent to POST /api/bridge/status */
export interface BridgeStatusPayload {
  event_code: string;
  connected: boolean;
  device_name?: string | null;
  /** Enriched status fields (optional, backward compatible) */
  circuit_breaker_state?: string | null;
  buffer_size?: number | null;
  plugin_id?: string | null;
  deck_count?: number | null;
  uptime_seconds?: number | null;
}

/** Enriched bridge status for detailed monitoring. */
export interface DetailedBridgeStatus {
  circuit_breaker_state: string;
  buffer_size: number;
  uptime_seconds: number;
}
