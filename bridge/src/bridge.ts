/**
 * Bridge logic for communicating with WrzDJ backend.
 *
 * Features:
 *   - Retry with exponential backoff on all API calls
 *   - AbortController timeouts on all fetch requests
 *   - Circuit breaker to avoid hammering an unreachable backend
 *   - Retry logic on DELETE (clearNowPlaying)
 */
import { config } from "./config.js";
import { CircuitBreaker } from "./circuit-breaker.js";
import {
  DELETE_BACKOFF_MS,
  DELETE_MAX_RETRIES,
  INITIAL_BACKOFF_MS,
  MAX_RETRIES,
  computeBackoff,
  fetchWithTimeout,
  sleep,
} from "./http-retry.js";
import { Logger } from "./logger.js";
import { TrackHistoryBuffer } from "./track-history-buffer.js";
import type { BridgeStatusPayload, DetailedBridgeStatus, NowPlayingPayload } from "./types.js";

const log = new Logger("Bridge");

/** Module start time for uptime calculation */
const startTime = Date.now();

/** Track key for deduplication (artist::title, lowercase) */
let lastTrackKey: string | null = null;

/** Timestamp of last successful POST */
let lastPostTime = 0;

/** Circuit breaker for backend communication */
const circuitBreaker = new CircuitBreaker({ failureThreshold: 3, cooldownMs: 60_000 });

/** Buffer for tracks that failed to post (replayed on backend recovery) */
const trackBuffer = new TrackHistoryBuffer();

circuitBreaker.on("stateChange", ({ from, to }: { from: string; to: string }) => {
  if (to === "OPEN") {
    log.error("Circuit breaker OPEN — backend unreachable, pausing API calls for 60s");
  } else if (to === "HALF_OPEN") {
    log.info("Circuit breaker HALF_OPEN — probing backend...");
  } else if (to === "CLOSED" && from !== "CLOSED") {
    log.info("Circuit breaker CLOSED — backend recovered");
    replayBufferedTracks();
  }
});

/** Get the circuit breaker instance (for external monitoring). */
export function getCircuitBreaker(): CircuitBreaker {
  return circuitBreaker;
}

/** Get enriched bridge status for backend reporting. */
export function getDetailedStatus(): DetailedBridgeStatus {
  return {
    circuit_breaker_state: circuitBreaker.getState(),
    buffer_size: trackBuffer.size,
    uptime_seconds: Math.floor((Date.now() - startTime) / 1000),
  };
}

/**
 * Generate a unique key for a track (used for deduplication).
 */
function makeTrackKey(artist: string, title: string): string {
  return `${artist.toLowerCase().trim()}::${title.toLowerCase().trim()}`;
}

/**
 * Check if we should skip this track (duplicate or too soon).
 */
export function shouldSkipTrack(artist: string, title: string): boolean {
  // Skip if no title
  if (!title) {
    return true;
  }

  // Skip if same track as last
  const key = makeTrackKey(artist, title);
  if (key === lastTrackKey) {
    return true;
  }

  // Debounce rapid changes (5 second cooldown)
  const now = Date.now();
  if (now - lastPostTime < config.minPlaySeconds * 1000) {
    log.debug(
      `Debouncing track change (${now - lastPostTime}ms since last, threshold: ${config.minPlaySeconds}s)`
    );
    return true;
  }

  return false;
}

/**
 * Update the last track info after successful POST.
 */
export function updateLastTrack(artist: string, title: string): void {
  lastTrackKey = makeTrackKey(artist, title);
  lastPostTime = Date.now();
}

/**
 * Make an HTTP POST with retry logic and circuit breaker.
 * Returns true if the request succeeded, false if it failed after all retries.
 */
async function postWithRetry(
  endpoint: string,
  payload: NowPlayingPayload | BridgeStatusPayload,
): Promise<boolean> {
  if (!circuitBreaker.allowRequest()) {
    log.warn(`POST ${endpoint} skipped — circuit breaker OPEN`);
    return false;
  }

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetchWithTimeout(`${config.apiUrl}${endpoint}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Bridge-API-Key": config.apiKey,
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`HTTP ${response.status}: ${text}`);
      }

      log.info(`POST ${endpoint} succeeded`);
      circuitBreaker.recordSuccess();
      return true;
    } catch (err) {
      lastError = err as Error;
      if (attempt < MAX_RETRIES) {
        const backoff = computeBackoff(INITIAL_BACKOFF_MS, attempt);
        log.warn(`Retry ${attempt + 1}/${MAX_RETRIES} in ${backoff}ms: ${lastError.message}`);
        await sleep(backoff);
      }
    }
  }

  circuitBreaker.recordFailure();
  log.error(`POST ${endpoint} failed after ${MAX_RETRIES + 1} attempts: ${lastError?.message}`);
  return false;
}

/**
 * Post a now-playing update to the backend.
 * Returns true if the backend acknowledged the update.
 * Failed payloads are buffered for replay when the backend recovers.
 */
export async function postNowPlaying(
  title: string,
  artist: string,
  album?: string,
  deck?: string,
  source?: string,
): Promise<boolean> {
  const payload: NowPlayingPayload = {
    event_code: config.eventCode,
    title,
    artist,
    album: album ?? null,
    deck: deck ?? null,
    source: source ?? null,
  };

  log.info(`Now Playing: "${title}" by ${artist}`);
  const success = await postWithRetry("/api/bridge/nowplaying", payload);
  if (!success) {
    trackBuffer.push(payload);
    log.info(`Buffered track for replay (${trackBuffer.size} in buffer)`);
  }
  return success;
}

/**
 * Replay buffered tracks that failed during backend downtime.
 * Called automatically when the circuit breaker closes.
 */
async function replayBufferedTracks(): Promise<void> {
  const tracks = trackBuffer.drain();
  if (tracks.length === 0) return;

  log.info(`Replaying ${tracks.length} buffered track(s)...`);
  for (const { payload } of tracks) {
    const replayPayload = { ...payload, delayed: true };
    const success = await postWithRetry("/api/bridge/nowplaying", replayPayload);
    if (!success) {
      log.warn(`Replay failed for "${payload.title}" — backend may be down again`);
      return; // Stop replaying if backend goes down again
    }
    log.info(`Replayed: "${payload.title}" by ${payload.artist}`);
  }
}

/**
 * Clear now-playing on the backend (authoritative clear on disconnect/shutdown).
 * Retries up to DELETE_MAX_RETRIES times with backoff.
 */
export async function clearNowPlaying(): Promise<void> {
  const endpoint = `/api/bridge/nowplaying/${config.eventCode}`;

  for (let attempt = 0; attempt <= DELETE_MAX_RETRIES; attempt++) {
    try {
      const response = await fetchWithTimeout(`${config.apiUrl}${endpoint}`, {
        method: "DELETE",
        headers: {
          "X-Bridge-API-Key": config.apiKey,
        },
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`HTTP ${response.status}: ${text}`);
      }

      log.info(`DELETE ${endpoint} succeeded`);
      return;
    } catch (err) {
      const message = (err as Error).message;
      if (attempt < DELETE_MAX_RETRIES) {
        const backoff = computeBackoff(DELETE_BACKOFF_MS, attempt);
        log.warn(`DELETE ${endpoint} retry ${attempt + 1}/${DELETE_MAX_RETRIES} in ${backoff}ms: ${message}`);
        await sleep(backoff);
      } else {
        log.error(`DELETE ${endpoint} failed after ${DELETE_MAX_RETRIES + 1} attempts: ${message}`);
      }
    }
  }
}

/**
 * Post bridge connection status to the backend.
 * Returns true if the backend acknowledged the status update.
 * Accepts optional enriched fields for detailed monitoring.
 */
export async function postBridgeStatus(
  connected: boolean,
  deviceName?: string,
  enriched?: Partial<DetailedBridgeStatus> & { plugin_id?: string; deck_count?: number },
): Promise<boolean> {
  const payload: BridgeStatusPayload = {
    event_code: config.eventCode,
    connected,
    device_name: deviceName ?? null,
    circuit_breaker_state: enriched?.circuit_breaker_state ?? null,
    buffer_size: enriched?.buffer_size ?? null,
    plugin_id: enriched?.plugin_id ?? null,
    deck_count: enriched?.deck_count ?? null,
    uptime_seconds: enriched?.uptime_seconds ?? null,
  };

  log.info(
    `Status: ${connected ? "Connected" : "Disconnected"}${deviceName ? ` (${deviceName})` : ""}`
  );
  return postWithRetry("/api/bridge/status", payload);
}
