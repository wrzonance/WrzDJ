/**
 * Circular buffer for storing track payloads that failed to reach the backend.
 *
 * When the backend is unreachable (circuit breaker OPEN), tracks that the DJ
 * plays are lost. This buffer captures them so they can be replayed when
 * connectivity recovers.
 *
 * Replayed tracks include a `delayed: true` flag so the backend can handle
 * them appropriately (e.g., add to play history without triggering kiosk
 * now-playing updates).
 */
import type { NowPlayingPayload } from "./types.js";

export interface BufferedTrack {
  readonly payload: NowPlayingPayload;
  readonly timestamp: number;
}

const DEFAULT_CAPACITY = 20;

export class TrackHistoryBuffer {
  private readonly buffer: BufferedTrack[] = [];
  private readonly capacity: number;

  constructor(capacity: number = DEFAULT_CAPACITY) {
    this.capacity = capacity;
  }

  /** Add a failed track payload to the buffer. */
  push(payload: NowPlayingPayload): void {
    if (this.buffer.length >= this.capacity) {
      this.buffer.shift();
    }
    this.buffer.push({ payload, timestamp: Date.now() });
  }

  /** Get all buffered tracks and clear the buffer. */
  drain(): readonly BufferedTrack[] {
    const items = [...this.buffer];
    this.buffer.length = 0;
    return items;
  }

  /**
   * Put tracks back at the front, in order, ahead of anything pushed since they were drained
   * (a replay that failed partway, #961). Over capacity, the oldest are dropped, as in push().
   */
  requeueFront(items: readonly BufferedTrack[]): void {
    this.buffer.unshift(...items);
    while (this.buffer.length > this.capacity) {
      this.buffer.shift();
    }
  }

  /** Number of buffered tracks. */
  get size(): number {
    return this.buffer.length;
  }

  /** Clear all buffered tracks without returning them. */
  clear(): void {
    this.buffer.length = 0;
  }
}
