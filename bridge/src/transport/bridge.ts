/**
 * Bridge logic for communicating with WrzDJ backend.
 *
 * Features:
 *   - Retry with exponential backoff on all API calls
 *   - AbortController timeouts on all fetch requests
 *   - Circuit breaker to avoid hammering an unreachable backend
 *   - Retry logic on DELETE (clearNowPlaying)
 */
import { CircuitBreaker } from "./circuit-breaker.js";
import { MILLISECONDS_PER_SECOND } from "../shared/time-units.js";
import {
  DELETE_BACKOFF_MS,
  DELETE_MAX_RETRIES,
  INITIAL_BACKOFF_MS,
  MAX_RETRIES,
  computeBackoff,
  fetchWithTimeout,
  sleep,
} from "./http-retry.js";
import { Logger } from "../shared/logger.js";
import { TrackHistoryBuffer } from "./track-history-buffer.js";
import type { BridgeStatusPayload, DetailedBridgeStatus, NowPlayingPayload } from "./types.js";

interface BridgeClientConfig {
  readonly apiUrl: string;
  readonly apiKey: string;
  readonly eventCode: string;
  readonly minPlaySeconds: number;
}

function toError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}

/** HTTP client and playback delivery state for one bridge session. */
export class BridgeClient {
  private readonly config: BridgeClientConfig;


  private readonly log = new Logger("Bridge");

  /** Module start time for uptime calculation */
  private readonly startTime = Date.now();

  /** Track key for deduplication (artist::title, lowercase) */
  private lastTrackKey: string | null = null;

  /** Timestamp of last successful POST */
  private lastPostTime = 0;

  /** Circuit breaker for backend communication */
  private readonly circuitBreaker = new CircuitBreaker({ failureThreshold: 3, cooldownMs: 60_000 });

  /** Buffer for tracks that failed to post (replayed on backend recovery) */
  private readonly trackBuffer = new TrackHistoryBuffer();

  constructor(
    config: BridgeClientConfig,
    private readonly onUnauthorized?: () => void,
  ) {
    this.config = { ...config };
    this.circuitBreaker.on("stateChange", ({ from, to }) => {
      if (to === "OPEN") {
        this.log.error("Circuit breaker OPEN — backend unreachable, pausing API calls for 60s");
      } else if (to === "HALF_OPEN") {
        this.log.info("Circuit breaker HALF_OPEN — probing backend...");
      } else if (to === "CLOSED" && from !== "CLOSED") {
        this.log.info("Circuit breaker CLOSED — backend recovered");
        this.replayBufferedTracks();
      }
    });
  }

  /** Get the circuit breaker instance (for external monitoring). */
  getCircuitBreaker(): CircuitBreaker {
    return this.circuitBreaker;
  }

  /** Get enriched bridge status for backend reporting. */
  getDetailedStatus(): DetailedBridgeStatus {
    return {
      circuit_breaker_state: this.circuitBreaker.getState(),
      buffer_size: this.trackBuffer.size,
      uptime_seconds: Math.floor((Date.now() - this.startTime) / MILLISECONDS_PER_SECOND),
    };
  }

  /**
   * Generate a unique key for a track (used for deduplication).
   */
  private makeTrackKey(artist: string, title: string): string {
    return `${artist.toLowerCase().trim()}::${title.toLowerCase().trim()}`;
  }

  /**
   * Check if we should skip this track (duplicate or too soon).
   */
  shouldSkipTrack(artist: string, title: string): boolean {
    // Skip if no title
    if (!title) {
      return true;
    }

    // Skip if same track as last
    const key = this.makeTrackKey(artist, title);
    if (key === this.lastTrackKey) {
      return true;
    }

    // Debounce rapid changes (5 second cooldown)
    const now = Date.now();
    if (now - this.lastPostTime < this.config.minPlaySeconds * MILLISECONDS_PER_SECOND) {
      this.log.debug(
        `Debouncing track change (${now - this.lastPostTime}ms since last, threshold: ${this.config.minPlaySeconds}s)`
      );
      return true;
    }

    return false;
  }

  /**
   * Update the last track info after successful POST.
   */
  updateLastTrack(artist: string, title: string): void {
    this.lastTrackKey = this.makeTrackKey(artist, title);
    this.lastPostTime = Date.now();
  }

  /**
   * Make an HTTP POST with retry logic and circuit breaker.
   * Returns true if the request succeeded, false if it failed after all retries.
   */
  private async postWithRetry(
    endpoint: string,
    payload: NowPlayingPayload | BridgeStatusPayload,
  ): Promise<boolean> {
    const admission = this.circuitBreaker.beginRequest();
    if (!admission) {
      this.log.warn(`POST ${endpoint} skipped — circuit breaker OPEN`);
      return false;
    }

    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const response = await fetchWithTimeout(`${this.config.apiUrl}${endpoint}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Bridge-API-Key": this.config.apiKey,
          },
          body: JSON.stringify(payload),
        });

        if (response.status === 401 && this.onUnauthorized) {
          this.circuitBreaker.recordSuccess(admission);
          this.log.error(`POST ${endpoint} returned 401 — session expired`);
          this.onUnauthorized();
          return false;
        }

        if (!response.ok) {
          const text = await response.text();
          throw new Error(`HTTP ${response.status}: ${text}`);
        }

        this.log.info(`POST ${endpoint} succeeded`);
        this.circuitBreaker.recordSuccess(admission);
        return true;
      } catch (err) {
        lastError = toError(err);
        if (attempt < MAX_RETRIES) {
          const backoff = computeBackoff(INITIAL_BACKOFF_MS, attempt);
          this.log.warn(`Retry ${attempt + 1}/${MAX_RETRIES} in ${backoff}ms: ${lastError.message}`);
          await sleep(backoff);
        }
      }
    }

    this.circuitBreaker.recordFailure(admission);
    this.log.error(`POST ${endpoint} failed after ${MAX_RETRIES + 1} attempts: ${lastError?.message}`);
    return false;
  }

  /**
   * Post a now-playing update to the backend.
   * Returns true if the backend acknowledged the update.
   * Failed payloads are buffered for replay when the backend recovers.
   */
  async postNowPlaying(
    title: string,
    artist: string,
    album?: string,
    deck?: string,
    source?: string,
  ): Promise<boolean> {
    const payload: NowPlayingPayload = {
      event_code: this.config.eventCode,
      title,
      artist,
      album: album ?? null,
      deck: deck ?? null,
      source: source ?? null,
    };

    this.log.info(`Now Playing: "${title}" by ${artist}`);
    const success = await this.postWithRetry("/api/bridge/nowplaying", payload);
    if (!success) {
      this.trackBuffer.push(payload);
      this.log.info(`Buffered track for replay (${this.trackBuffer.size} in buffer)`);
    }
    return success;
  }

  /**
   * Replay buffered tracks that failed during backend downtime.
   * Called automatically when the circuit breaker closes.
   */
  private replayBufferedTracks(): void {
    void this.trackBuffer.replay(async ({ payload }) => {
      const success = await this.postWithRetry("/api/bridge/nowplaying", { ...payload, delayed: true });
      if (success) this.log.info(`Replayed: "${payload.title}" by ${payload.artist}`);
      else this.log.warn(`Replay failed for "${payload.title}" — retaining unsent tracks`);
      return success;
    }).catch((error: unknown) => {
      this.log.error(`Replay failed: ${error instanceof Error ? error.message : String(error)}`);
    });
  }

  /**
   * Clear now-playing on the backend (authoritative clear on disconnect/shutdown).
   * Retries up to DELETE_MAX_RETRIES times with backoff.
   * Returns whether the backend acknowledged the clear.
   */
  async clearNowPlaying(): Promise<boolean> {
    const endpoint = `/api/bridge/nowplaying/${this.config.eventCode}`;

    for (let attempt = 0; attempt <= DELETE_MAX_RETRIES; attempt++) {
      try {
        const response = await fetchWithTimeout(`${this.config.apiUrl}${endpoint}`, {
          method: "DELETE",
          headers: {
            "X-Bridge-API-Key": this.config.apiKey,
          },
        });

        if (response.status === 401 && this.onUnauthorized) {
          this.log.error(`DELETE ${endpoint} returned 401 — session expired`);
          this.onUnauthorized();
          return false;
        }

        if (!response.ok) {
          const text = await response.text();
          throw new Error(`HTTP ${response.status}: ${text}`);
        }

        this.log.info(`DELETE ${endpoint} succeeded`);
        return true;
      } catch (err) {
        const message = toError(err).message;
        if (attempt < DELETE_MAX_RETRIES) {
          const backoff = computeBackoff(DELETE_BACKOFF_MS, attempt);
          this.log.warn(`DELETE ${endpoint} retry ${attempt + 1}/${DELETE_MAX_RETRIES} in ${backoff}ms: ${message}`);
          await sleep(backoff);
        } else {
          this.log.error(`DELETE ${endpoint} failed after ${DELETE_MAX_RETRIES + 1} attempts: ${message}`);
        }
      }
    }
    return false;
  }

  /**
   * Post bridge connection status to the backend.
   * Returns true if the backend acknowledged the status update.
   * Accepts optional enriched fields for detailed monitoring.
   */
  postBridgeStatus(
    connected: boolean,
    deviceName?: string,
    enriched?: Partial<DetailedBridgeStatus> & { plugin_id?: string; deck_count?: number; },
  ): Promise<boolean> {
    const payload: BridgeStatusPayload = {
      event_code: this.config.eventCode,
      connected,
      device_name: deviceName ?? null,
      circuit_breaker_state: enriched?.circuit_breaker_state ?? null,
      buffer_size: enriched?.buffer_size ?? null,
      plugin_id: enriched?.plugin_id ?? null,
      deck_count: enriched?.deck_count ?? null,
      uptime_seconds: enriched?.uptime_seconds ?? null,
    };

    this.log.info(
      `Status: ${connected ? "Connected" : "Disconnected"}${deviceName ? ` (${deviceName})` : ""}`
    );
    return this.postWithRetry("/api/bridge/status", payload);
  }

}
