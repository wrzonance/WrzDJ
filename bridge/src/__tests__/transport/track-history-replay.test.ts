import { describe, expect, it, vi } from "vitest";
import { TrackHistoryBuffer } from "../../transport/track-history-buffer.js";
import type { NowPlayingPayload } from "../../transport/types.js";

const payload = (title: string): NowPlayingPayload => ({ event_code: "TEST", title, artist: "Artist", album: null, deck: null });

describe("track history replay", () => {
  // Regression: 57cfcdc6867f drained the entire history before confirming delivery.
  it("retains failed and unsent tracks and resumes in order", async () => {
    const buffer = new TrackHistoryBuffer();
    for (const title of ["A", "B", "C"]) buffer.push(payload(title));
    const send = vi.fn().mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    await buffer.replay(send);
    expect(buffer.size).toBe(2);
    const retry = vi.fn().mockResolvedValue(true);
    await buffer.replay(retry);
    expect(retry.mock.calls.map(([entry]) => entry.payload.title)).toEqual(["B", "C"]);
    expect(buffer.size).toBe(0);
  });

  it("preserves entries if the sender throws", async () => {
    const buffer = new TrackHistoryBuffer();
    buffer.push(payload("A"));
    await expect(buffer.replay(async () => { throw new Error("offline"); })).rejects.toThrow("offline");
    expect(buffer.size).toBe(1);
  });

  it("coalesces replay calls and does not delete newly buffered tracks after eviction", async () => {
    const buffer = new TrackHistoryBuffer(2);
    buffer.push(payload("A"));
    buffer.push(payload("B"));
    let acknowledge!: (success: boolean) => void;
    const send = vi.fn().mockImplementationOnce(() => new Promise<boolean>(resolve => { acknowledge = resolve; })).mockResolvedValue(true);
    const first = buffer.replay(send);
    await Promise.resolve();
    const second = buffer.replay(send);
    buffer.push(payload("C"));
    acknowledge(true);
    await Promise.all([first, second]);
    expect(send.mock.calls.map(([entry]) => entry.payload.title)).toEqual(["A", "B", "C"]);
    expect(buffer.size).toBe(0);
  });

  it("does not replay a new session after clear during an in-flight request", async () => {
    const buffer = new TrackHistoryBuffer();
    buffer.push(payload("Old"));
    let acknowledge!: (success: boolean) => void;
    const send = vi.fn(() => new Promise<boolean>(resolve => { acknowledge = resolve; }));
    const replay = buffer.replay(send);
    await Promise.resolve();
    buffer.clear();
    buffer.push(payload("New"));
    acknowledge(true);
    await replay;
    expect(send).toHaveBeenCalledOnce();
    expect(buffer.size).toBe(1);
  });
});
