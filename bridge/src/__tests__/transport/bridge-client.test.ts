import { afterEach, describe, expect, it, vi } from "vitest";
import { BridgeClient } from "../../transport/bridge.js";
import { loadConfig } from "../../runtime/config.js";
import type { CircuitBreaker } from "../../transport/circuit-breaker.js";

function recordFailures(breaker: CircuitBreaker, count: number): void {
  for (let i = 0; i < count; i++) {
    const admission = breaker.beginRequest();
    if (!admission) throw new Error("Expected request admission");
    breaker.recordFailure(admission);
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("BridgeClient isolation", () => {
  it("retains every buffered track when recovery fails again during replay", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const client = new BridgeClient(loadConfig({ WRZDJ_BRIDGE_API_KEY: "key", WRZDJ_EVENT_CODE: "TEST" }));
    const breaker = client.getCircuitBreaker();
    recordFailures(breaker, 3);
    await client.postNowPlaying("A", "Artist");
    await client.postNowPlaying("B", "Artist");
    vi.advanceTimersByTime(60_000);
    fetch.mockResolvedValueOnce(new Response("", { status: 200 })).mockRejectedValue(new Error("offline again"));
    await client.postBridgeStatus(true);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(client.getDetailedStatus().buffer_size).toBe(2);
    breaker.reset();
    recordFailures(breaker, 3);
    vi.advanceTimersByTime(60_000);
    fetch.mockClear().mockResolvedValue(new Response("", { status: 200 }));
    await client.postBridgeStatus(true);
    await vi.advanceTimersByTimeAsync(1);
    expect(client.getDetailedStatus().buffer_size).toBe(0);
    const replayed = fetch.mock.calls.filter(([url]) => url.endsWith("/nowplaying"));
    expect(replayed.map(([, options]) => JSON.parse(options.body).title)).toEqual(["A", "B"]);
  });

  // Regression: 57cfcdc6867f shared config, deduplication and circuit state globally.
  it("keeps destinations, authentication and playback state independent", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const first = new BridgeClient(loadConfig({ WRZDJ_BRIDGE_API_KEY: "key-one", WRZDJ_EVENT_CODE: "ONE" }));
    const second = new BridgeClient(loadConfig({
      WRZDJ_API_URL: "https://second.example", WRZDJ_BRIDGE_API_KEY: "key-two", WRZDJ_EVENT_CODE: "TWO",
    }));
    first.updateLastTrack("Artist", "Track");
    expect(second.shouldSkipTrack("Artist", "Track")).toBe(false);
    await second.postNowPlaying("Track", "Artist");
    expect(fetch).toHaveBeenCalledWith("https://second.example/api/bridge/nowplaying", expect.objectContaining({
      headers: expect.objectContaining({ "X-Bridge-API-Key": "key-two" }),
      body: expect.stringContaining('"event_code":"TWO"'),
    }));
    recordFailures(first.getCircuitBreaker(), 3);
    expect(second.getCircuitBreaker().getState()).toBe("CLOSED");
  });
});
