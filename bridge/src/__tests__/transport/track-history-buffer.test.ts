import { describe, it, expect } from "vitest";
import { TrackHistoryBuffer } from "../../transport/track-history-buffer.js";
import type { NowPlayingPayload } from "../../transport/types.js";

function makePayload(title: string, artist = "Artist"): NowPlayingPayload {
  return { event_code: "TEST", title, artist, album: null, deck: null };
}

describe("TrackHistoryBuffer", () => {
  it("starts empty", () => {
    const buf = new TrackHistoryBuffer();
    expect(buf.size).toBe(0);
    expect(buf.drain()).toEqual([]);
  });

  it("stores pushed payloads", () => {
    const buf = new TrackHistoryBuffer();
    buf.push(makePayload("Track A"));
    buf.push(makePayload("Track B"));

    expect(buf.size).toBe(2);
  });

  it("drain returns all items and clears buffer", () => {
    const buf = new TrackHistoryBuffer();
    buf.push(makePayload("Track A"));
    buf.push(makePayload("Track B"));

    const items = buf.drain();
    expect(items).toHaveLength(2);
    expect(items[0]!.payload.title).toBe("Track A");
    expect(items[1]!.payload.title).toBe("Track B");
    expect(buf.size).toBe(0);
  });

  it("includes timestamps on buffered items", () => {
    const buf = new TrackHistoryBuffer();
    const before = Date.now();
    buf.push(makePayload("Track A"));
    const after = Date.now();

    const items = buf.drain();
    expect(items[0]!.timestamp).toBeGreaterThanOrEqual(before);
    expect(items[0]!.timestamp).toBeLessThanOrEqual(after);
  });

  it("evicts oldest when capacity exceeded", () => {
    const buf = new TrackHistoryBuffer(3);
    buf.push(makePayload("Track 1"));
    buf.push(makePayload("Track 2"));
    buf.push(makePayload("Track 3"));
    buf.push(makePayload("Track 4"));

    expect(buf.size).toBe(3);
    const items = buf.drain();
    expect(items[0]!.payload.title).toBe("Track 2");
    expect(items[2]!.payload.title).toBe("Track 4");
  });

  it("clear empties the buffer without returning items", () => {
    const buf = new TrackHistoryBuffer();
    buf.push(makePayload("Track A"));
    buf.push(makePayload("Track B"));

    buf.clear();
    expect(buf.size).toBe(0);
    expect(buf.drain()).toEqual([]);
  });

  it("uses default capacity of 20", () => {
    const buf = new TrackHistoryBuffer();
    for (let i = 0; i < 25; i++) {
      buf.push(makePayload(`Track ${i}`));
    }

    expect(buf.size).toBe(20);
    const items = buf.drain();
    expect(items[0]!.payload.title).toBe("Track 5");
    expect(items[19]!.payload.title).toBe("Track 24");
  });

  it("drain returns readonly array", () => {
    const buf = new TrackHistoryBuffer();
    buf.push(makePayload("Track A"));
    const items = buf.drain();

    // TypeScript enforces readonly, but verify it's a copy
    expect(buf.size).toBe(0);
    expect(items).toHaveLength(1);
  });
});
