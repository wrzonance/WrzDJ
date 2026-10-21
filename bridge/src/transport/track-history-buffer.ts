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
  private replayPromise: Promise<void> | null = null;
  private generation = 0;

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
    this.clear();
    return items;
  }

  /** Deliver in order, removing only acknowledged entries. Concurrent calls share the replay. */
  replay(send: (track: BufferedTrack) => Promise<boolean>): Promise<void> {
    if (!this.replayPromise) {
      const generation = this.generation;
      this.replayPromise = Promise.resolve().then(async () => {
        while (this.buffer.length > 0 && generation === this.generation) {
          const track = this.buffer[0]!;
          if (!await send(track)) return;
          // New arrivals may evict this entry while the request is in flight.
          const index = this.buffer.indexOf(track);
          if (index >= 0) this.buffer.splice(index, 1);
        }
      }).finally(() => { this.replayPromise = null; });
    }
    return this.replayPromise;
  }

  /** Number of buffered tracks. */
  get size(): number {
    return this.buffer.length;
  }

  /** Clear all buffered tracks without returning them. */
  clear(): void {
    this.generation += 1;
    this.buffer.length = 0;
  }
}
