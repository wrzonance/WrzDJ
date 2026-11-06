/**
 * Tests for bridge.ts — HTTP communication layer.
 *
 * Covers: postWithRetry, clearNowPlaying, postBridgeStatus, postNowPlaying,
 * shouldSkipTrack, updateLastTrack, fetch timeout, circuit breaker integration.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock config before importing bridge
vi.mock("../config.js", () => ({
  config: {
    apiUrl: "http://localhost:8000",
    apiKey: "test-api-key",
    eventCode: "TEST123",
    minPlaySeconds: 5,
  },
}));

// Mock global fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// Import after mocks are set up
import {
  shouldSkipTrack,
  updateLastTrack,
  postNowPlaying,
  clearNowPlaying,
  postBridgeStatus,
  getCircuitBreaker,
  getDetailedStatus,
} from "../bridge.js";

function createMockResponse(status: number, body = ""): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(body),
    headers: new Headers(),
    redirected: false,
    statusText: "",
    type: "basic",
    url: "",
    clone: () => ({}) as Response,
    body: null,
    bodyUsed: false,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
    blob: () => Promise.resolve(new Blob()),
    formData: () => Promise.resolve(new FormData()),
    json: () => Promise.resolve({}),
    bytes: () => Promise.resolve(new Uint8Array()),
  } as Response;
}

describe("bridge.ts", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockFetch.mockReset();
    // Reset circuit breaker between tests
    getCircuitBreaker().reset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("shouldSkipTrack", () => {
    it("skips tracks with no title", () => {
      expect(shouldSkipTrack("Artist", "")).toBe(true);
    });

    it("allows first track", () => {
      // Reset internal state by updating with something unique
      updateLastTrack("__reset__", "__reset__");
      // Advance past debounce window
      vi.advanceTimersByTime(6000);

      expect(shouldSkipTrack("Artist", "Title")).toBe(false);
    });

    it("skips duplicate tracks", () => {
      updateLastTrack("Artist", "Title");
      vi.advanceTimersByTime(6000);
      expect(shouldSkipTrack("Artist", "Title")).toBe(true);
    });

    it("skips tracks within debounce window", () => {
      updateLastTrack("Artist A", "Title A");
      // Don't advance past the 5s debounce
      vi.advanceTimersByTime(2000);
      expect(shouldSkipTrack("Artist B", "Title B")).toBe(true);
    });

    it("allows tracks after debounce window", () => {
      updateLastTrack("Artist A", "Title A");
      vi.advanceTimersByTime(6000);
      expect(shouldSkipTrack("Artist B", "Title B")).toBe(false);
    });

    it("is case-insensitive for deduplication", () => {
      updateLastTrack("Artist", "Title");
      vi.advanceTimersByTime(6000);
      expect(shouldSkipTrack("ARTIST", "TITLE")).toBe(true);
    });

    it("trims whitespace for deduplication", () => {
      updateLastTrack("Artist", "Title");
      vi.advanceTimersByTime(6000);
      expect(shouldSkipTrack("  Artist  ", "  Title  ")).toBe(true);
    });
  });

  describe("postNowPlaying", () => {
    it("posts now-playing update on success", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200));

      const result = await postNowPlaying("Track", "Artist", "Album", "1");

      expect(result).toBe(true);
      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, options] = mockFetch.mock.calls[0]!;
      expect(url).toBe("http://localhost:8000/api/bridge/nowplaying");
      expect(options.method).toBe("POST");
      expect(options.headers["Content-Type"]).toBe("application/json");
      expect(options.headers["X-Bridge-API-Key"]).toBe("test-api-key");
      const body = JSON.parse(options.body);
      expect(body).toEqual({
        event_code: "TEST123",
        title: "Track",
        artist: "Artist",
        album: "Album",
        deck: "1",
        source: null,
      });
    });

    it("returns false after retry exhaustion", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));

      const promise = postNowPlaying("Track", "Artist");

      // Advance through all retry backoffs: 2s, 4s, 8s
      await vi.advanceTimersByTimeAsync(2000);
      await vi.advanceTimersByTimeAsync(4000);
      await vi.advanceTimersByTimeAsync(8000);

      const result = await promise;
      expect(result).toBe(false);
      expect(mockFetch).toHaveBeenCalledTimes(4); // 1 initial + 3 retries
    });

    it("retries on HTTP 500", async () => {
      mockFetch
        .mockResolvedValueOnce(createMockResponse(500, "Internal Server Error"))
        .mockResolvedValueOnce(createMockResponse(200));

      const promise = postNowPlaying("Track", "Artist");
      await vi.advanceTimersByTimeAsync(2000);
      const result = await promise;

      expect(result).toBe(true);
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it("includes source in payload when provided", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200));

      await postNowPlaying("Track", "Artist", "Album", "1", "stagelinq");

      const body = JSON.parse(mockFetch.mock.calls[0]![1].body);
      expect(body.source).toBe("stagelinq");
    });

    it("sends correct source for each plugin type", async () => {
      const plugins = ["stagelinq", "pioneer", "serato", "traktor"];
      for (const plugin of plugins) {
        mockFetch.mockResolvedValue(createMockResponse(200));
        await postNowPlaying("Track", "Artist", undefined, undefined, plugin);
        const body = JSON.parse(
          mockFetch.mock.calls[mockFetch.mock.calls.length - 1]![1].body,
        );
        expect(body.source).toBe(plugin);
      }
    });

    it("defaults album and deck to null", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200));
      await postNowPlaying("Track", "Artist");

      const body = JSON.parse(mockFetch.mock.calls[0]![1].body);
      expect(body.album).toBeNull();
      expect(body.deck).toBeNull();
    });
  });

  describe("clearNowPlaying", () => {
    it("sends DELETE request", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200));

      await clearNowPlaying();

      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, options] = mockFetch.mock.calls[0]!;
      expect(url).toBe("http://localhost:8000/api/bridge/nowplaying/TEST123");
      expect(options.method).toBe("DELETE");
      expect(options.headers["X-Bridge-API-Key"]).toBe("test-api-key");
    });

    it("retries on failure (up to 2 retries)", async () => {
      mockFetch
        .mockRejectedValueOnce(new Error("Network error"))
        .mockRejectedValueOnce(new Error("Network error"))
        .mockResolvedValueOnce(createMockResponse(200));

      const promise = clearNowPlaying();
      await vi.advanceTimersByTimeAsync(1000); // 1st retry backoff
      await vi.advanceTimersByTimeAsync(2000); // 2nd retry backoff
      await promise;

      expect(mockFetch).toHaveBeenCalledTimes(3);
    });

    it("handles all retries failing gracefully", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));

      const promise = clearNowPlaying();
      await vi.advanceTimersByTimeAsync(1000);
      await vi.advanceTimersByTimeAsync(2000);
      // Should not throw
      await promise;

      expect(mockFetch).toHaveBeenCalledTimes(3); // 1 + 2 retries
    });

    it("retries on HTTP error response", async () => {
      mockFetch
        .mockResolvedValueOnce(createMockResponse(503, "Unavailable"))
        .mockResolvedValueOnce(createMockResponse(200));

      const promise = clearNowPlaying();
      await vi.advanceTimersByTimeAsync(1000);
      await promise;

      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });

  describe("postBridgeStatus", () => {
    it("posts connected status", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200));

      const result = await postBridgeStatus(true, "CDJ-2000");

      expect(result).toBe(true);
      const body = JSON.parse(mockFetch.mock.calls[0]![1].body);
      expect(body).toEqual({
        event_code: "TEST123",
        connected: true,
        device_name: "CDJ-2000",
        circuit_breaker_state: null,
        buffer_size: null,
        plugin_id: null,
        deck_count: null,
        uptime_seconds: null,
      });
    });

    it("posts disconnected status with null device name", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200));

      await postBridgeStatus(false);

      const body = JSON.parse(mockFetch.mock.calls[0]![1].body);
      expect(body.connected).toBe(false);
      expect(body.device_name).toBeNull();
    });
  });

  describe("circuit breaker integration", () => {
    it("opens circuit after 3 consecutive failures", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));

      // 1st full retry sequence (4 attempts)
      const p1 = postBridgeStatus(true);
      await vi.advanceTimersByTimeAsync(20_000);
      await p1;

      // 2nd full retry sequence
      const p2 = postBridgeStatus(true);
      await vi.advanceTimersByTimeAsync(20_000);
      await p2;

      // 3rd full retry sequence
      const p3 = postBridgeStatus(true);
      await vi.advanceTimersByTimeAsync(20_000);
      await p3;

      expect(getCircuitBreaker().getState()).toBe("OPEN");

      // 4th call should be skipped (circuit open)
      mockFetch.mockClear();
      const result = await postBridgeStatus(true);
      expect(result).toBe(false);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("recovers after cooldown", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));

      // Trip the circuit breaker
      for (let i = 0; i < 3; i++) {
        const p = postBridgeStatus(true);
        await vi.advanceTimersByTimeAsync(20_000);
        await p;
      }

      expect(getCircuitBreaker().getState()).toBe("OPEN");

      // Wait for cooldown (60s)
      vi.advanceTimersByTime(60_000);
      mockFetch.mockResolvedValue(createMockResponse(200));

      const result = await postBridgeStatus(true);
      expect(result).toBe(true);
      expect(getCircuitBreaker().getState()).toBe("CLOSED");
    });

    it("returns to OPEN if probe fails in HALF_OPEN", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));

      // Trip the circuit breaker
      for (let i = 0; i < 3; i++) {
        const p = postBridgeStatus(true);
        await vi.advanceTimersByTimeAsync(20_000);
        await p;
      }

      // Wait for cooldown
      vi.advanceTimersByTime(60_000);

      // Probe fails
      const p = postBridgeStatus(true);
      await vi.advanceTimersByTimeAsync(20_000);
      await p;

      expect(getCircuitBreaker().getState()).toBe("OPEN");
    });
  });

  describe("track history buffer", () => {
    it("buffers failed tracks and replays on circuit breaker recovery", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));

      // Buffer a track by failing all retries
      const p1 = postNowPlaying("Track A", "Artist A");
      await vi.advanceTimersByTimeAsync(20_000);
      const result = await p1;
      expect(result).toBe(false);

      // Trip the circuit breaker (need 3 failures total)
      const p2 = postBridgeStatus(true);
      await vi.advanceTimersByTimeAsync(20_000);
      await p2;

      const p3 = postBridgeStatus(true);
      await vi.advanceTimersByTimeAsync(20_000);
      await p3;

      expect(getCircuitBreaker().getState()).toBe("OPEN");

      // Wait for cooldown
      vi.advanceTimersByTime(60_000);

      // Backend recovers
      mockFetch.mockResolvedValue(createMockResponse(200));
      mockFetch.mockClear();

      // Trigger a request to close the circuit breaker (probe succeeds)
      const probeResult = await postBridgeStatus(true);
      expect(probeResult).toBe(true);

      // Allow replay to execute
      await vi.advanceTimersByTimeAsync(100);

      // Should have replayed the buffered track with delayed: true
      const replayCalls = mockFetch.mock.calls.filter((call) => {
        if (typeof call[0] !== "string") return false;
        if (!call[0].includes("/bridge/nowplaying")) return false;
        const body = JSON.parse(call[1].body);
        return body.delayed === true;
      });
      expect(replayCalls.length).toBeGreaterThanOrEqual(1);

      // Find the replayed "Track A" payload
      const trackAReplay = replayCalls.find((call) => {
        const body = JSON.parse(call[1].body);
        return body.title === "Track A";
      });
      expect(trackAReplay).toBeDefined();
      const replayBody = JSON.parse(trackAReplay![1].body);
      expect(replayBody.artist).toBe("Artist A");
      expect(replayBody.delayed).toBe(true);
    });
  });

  describe("replay that fails partway (#961)", () => {
    it("keeps the unsent tracks in the buffer", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));
      const before = getDetailedStatus().buffer_size;
      for (const title of ["R1", "R2", "R3", "R4", "R5"]) {
        const p = postNowPlaying(title, "Artist");
        await vi.advanceTimersByTimeAsync(20_000);
        expect(await p).toBe(false);
      }
      expect(getCircuitBreaker().getState()).toBe("OPEN");
      expect(getDetailedStatus().buffer_size).toBe(before + 5);

      // The backend is back, but the replay of R2 fails.
      vi.advanceTimersByTime(60_000);
      mockFetch.mockImplementation((_url: string, init: { body?: string }) => {
        const body = init.body ? JSON.parse(init.body) : {};
        return body.delayed && body.title === "R2"
          ? Promise.reject(new Error("Network error"))
          : Promise.resolve(createMockResponse(200));
      });
      expect(await postBridgeStatus(true)).toBe(true);
      await vi.advanceTimersByTimeAsync(20_000);

      expect(getDetailedStatus().buffer_size).toBe(4); // R2, R3, R4, R5
    });
  });

  describe("fetch timeout (AbortController)", () => {
    it("passes AbortSignal to fetch", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200));

      await postNowPlaying("Track", "Artist");

      const options = mockFetch.mock.calls[0]![1];
      expect(options.signal).toBeInstanceOf(AbortSignal);
    });

    it("treats AbortError as a retriable error", async () => {
      const abortError = new DOMException("The operation was aborted", "AbortError");
      mockFetch
        .mockRejectedValueOnce(abortError)
        .mockResolvedValueOnce(createMockResponse(200));

      const promise = postNowPlaying("Track", "Artist");
      await vi.advanceTimersByTimeAsync(2000); // Retry backoff
      const result = await promise;

      expect(result).toBe(true);
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });
});
