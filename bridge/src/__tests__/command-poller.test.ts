/**
 * Tests for CommandPoller — polls backend for pending bridge commands.
 *
 * Covers: polling lifecycle, command dispatch, circuit breaker respect,
 * error handling, multiple commands in single poll.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { EventEmitter } from "events";
import { CommandPoller } from "../command-poller.js";
import type { CircuitBreaker } from "../circuit-breaker.js";
import { Logger, setLogHandler, setMinLogLevel } from "../logger.js";

// Suppress log output during tests
setLogHandler(() => {});
setMinLogLevel("error");

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function createMockCircuitBreaker(allowRequest = true): CircuitBreaker {
  const emitter = new EventEmitter();
  return Object.assign(emitter, {
    allowRequest: vi.fn().mockReturnValue(allowRequest),
    recordSuccess: vi.fn(),
    recordFailure: vi.fn(),
    getState: vi.fn().mockReturnValue("CLOSED"),
    getConsecutiveFailures: vi.fn().mockReturnValue(0),
    reset: vi.fn(),
  }) as unknown as CircuitBreaker;
}

function createMockResponse(status: number, body: unknown = { commands: [] }): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
    json: () => Promise.resolve(body),
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
    bytes: () => Promise.resolve(new Uint8Array()),
  } as Response;
}

describe("CommandPoller", () => {
  let poller: CommandPoller;
  let cb: CircuitBreaker;
  let log: Logger;

  beforeEach(() => {
    vi.useFakeTimers();
    mockFetch.mockReset();
    cb = createMockCircuitBreaker();
    log = new Logger("Test");
    poller = new CommandPoller(cb, log);
  });

  afterEach(() => {
    poller.stop();
    vi.useRealTimers();
  });

  describe("lifecycle", () => {
    it("starts and stops polling", () => {
      expect(poller.isPolling).toBe(false);

      poller.start("http://localhost:8000", "key", "EVT1");
      expect(poller.isPolling).toBe(true);

      poller.stop();
      expect(poller.isPolling).toBe(false);
    });

    it("does not start twice", () => {
      poller.start("http://localhost:8000", "key", "EVT1");
      poller.start("http://localhost:8000", "key", "EVT1");
      expect(poller.isPolling).toBe(true);

      // Stopping once should fully stop
      poller.stop();
      expect(poller.isPolling).toBe(false);
    });

    it("cleans up interval on stop", () => {
      poller.start("http://localhost:8000", "key", "EVT1");
      poller.stop();

      // Advancing timers should not trigger any fetch
      mockFetch.mockResolvedValue(createMockResponse(200, { commands: [] }));
      vi.advanceTimersByTime(10_000);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("stop is safe to call when not started", () => {
      expect(() => poller.stop()).not.toThrow();
    });
  });

  describe("command dispatch", () => {
    it("emits command events for each command returned", async () => {
      const commands = [{ command_id: "1", command_type: "reset_decks" }, { command_id: "2", command_type: "reconnect" }];
      mockFetch.mockResolvedValue(createMockResponse(200, { commands }));

      const received: string[] = [];
      poller.on("command", (type: string) => received.push(type));

      poller.start("http://localhost:8000", "key", "EVT1");

      // Trigger the poll interval
      await vi.advanceTimersByTimeAsync(5_000);

      expect(received).toEqual(["reset_decks", "reconnect"]);
    });

    it("emits the full command as the second argument", async () => {
      const command = {
        command_id: "1",
        command_type: "setbuilder_transport",
        payload: { action: "play", track_id: "tidal:1" },
      };
      mockFetch.mockResolvedValue(createMockResponse(200, { commands: [command] }));

      const received: unknown[] = [];
      poller.on("command", (_type: string, cmd: unknown) => received.push(cmd));

      poller.start("http://localhost:8000", "key", "EVT1");
      await vi.advanceTimersByTimeAsync(5_000);

      expect(received).toEqual([command]);
    });

    it("sends correct URL and headers", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200, { commands: [] }));

      poller.start("http://localhost:8000", "test-key", "ABC123");
      await vi.advanceTimersByTimeAsync(5_000);

      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, options] = mockFetch.mock.calls[0]!;
      expect(url).toBe("http://localhost:8000/api/bridge/commands/ABC123");
      expect(options.method).toBe("GET");
      expect(options.headers["X-Bridge-API-Key"]).toBe("test-key");
    });

    it("emits nothing for empty command list", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200, { commands: [] }));

      const received: string[] = [];
      poller.on("command", (type: string) => received.push(type));

      poller.start("http://localhost:8000", "key", "EVT1");
      await vi.advanceTimersByTimeAsync(5_000);

      expect(received).toEqual([]);
    });

    it("records success on circuit breaker after successful poll", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200, { commands: [] }));

      poller.start("http://localhost:8000", "key", "EVT1");
      await vi.advanceTimersByTimeAsync(5_000);

      expect(cb.recordSuccess).toHaveBeenCalledOnce();
    });
  });

  describe("circuit breaker respect", () => {
    it("skips poll when circuit breaker disallows requests", async () => {
      cb = createMockCircuitBreaker(false);
      poller = new CommandPoller(cb, log);

      poller.start("http://localhost:8000", "key", "EVT1");
      await vi.advanceTimersByTimeAsync(5_000);

      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("resumes polling when circuit breaker allows again", async () => {
      const allowFn = vi.fn().mockReturnValue(false);
      cb = createMockCircuitBreaker();
      (cb.allowRequest as ReturnType<typeof vi.fn>) = allowFn;
      poller = new CommandPoller(cb, log);

      poller.start("http://localhost:8000", "key", "EVT1");

      // First poll — blocked
      await vi.advanceTimersByTimeAsync(5_000);
      expect(mockFetch).not.toHaveBeenCalled();

      // Circuit breaker opens
      allowFn.mockReturnValue(true);
      mockFetch.mockResolvedValue(createMockResponse(200, { commands: [{ command_id: "3", command_type: "restart" }] }));

      const received: string[] = [];
      poller.on("command", (type: string) => received.push(type));

      // Second poll — allowed
      await vi.advanceTimersByTimeAsync(5_000);
      expect(mockFetch).toHaveBeenCalledOnce();
      expect(received).toEqual(["restart"]);
    });
  });

  describe("error handling", () => {
    it("does not crash on network error", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));

      poller.start("http://localhost:8000", "key", "EVT1");
      await vi.advanceTimersByTimeAsync(5_000);

      // Poller should still be running
      expect(poller.isPolling).toBe(true);
    });

    it("does not crash on HTTP error response", async () => {
      mockFetch.mockResolvedValue(createMockResponse(500, "Internal Server Error"));

      poller.start("http://localhost:8000", "key", "EVT1");
      await vi.advanceTimersByTimeAsync(5_000);

      expect(poller.isPolling).toBe(true);
    });

    it("does not record success on HTTP error", async () => {
      mockFetch.mockResolvedValue(createMockResponse(500, "Error"));

      poller.start("http://localhost:8000", "key", "EVT1");
      await vi.advanceTimersByTimeAsync(5_000);

      expect(cb.recordSuccess).not.toHaveBeenCalled();
    });

    it("continues polling after error", async () => {
      mockFetch
        .mockRejectedValueOnce(new Error("Network error"))
        .mockResolvedValueOnce(createMockResponse(200, { commands: [{ command_id: "1", command_type: "reset_decks" }] }));

      const received: string[] = [];
      poller.on("command", (type: string) => received.push(type));

      poller.start("http://localhost:8000", "key", "EVT1");

      // First poll fails
      await vi.advanceTimersByTimeAsync(5_000);
      expect(received).toEqual([]);

      // Second poll succeeds
      await vi.advanceTimersByTimeAsync(5_000);
      expect(received).toEqual(["reset_decks"]);
    });

    it("uses AbortController timeout", async () => {
      mockFetch.mockResolvedValue(createMockResponse(200, { commands: [] }));

      poller.start("http://localhost:8000", "key", "EVT1");
      await vi.advanceTimersByTimeAsync(5_000);

      const options = mockFetch.mock.calls[0]![1];
      expect(options.signal).toBeInstanceOf(AbortSignal);
    });
  });

  describe("multiple commands", () => {
    it("emits all commands from a single poll response", async () => {
      const commands = [
        { command_id: "1", command_type: "reset_decks" },
        { command_id: "2", command_type: "reconnect" },
        { command_id: "3", command_type: "restart" },
      ];
      mockFetch.mockResolvedValue(createMockResponse(200, { commands }));

      const received: string[] = [];
      poller.on("command", (type: string) => received.push(type));

      poller.start("http://localhost:8000", "key", "EVT1");
      await vi.advanceTimersByTimeAsync(5_000);

      expect(received).toEqual(["reset_decks", "reconnect", "restart"]);
    });

    it("handles commands across multiple poll cycles", async () => {
      mockFetch
        .mockResolvedValueOnce(createMockResponse(200, { commands: [{ command_id: "1", command_type: "reset_decks" }] }))
        .mockResolvedValueOnce(createMockResponse(200, { commands: [{ command_id: "3", command_type: "restart" }] }));

      const received: string[] = [];
      poller.on("command", (type: string) => received.push(type));

      poller.start("http://localhost:8000", "key", "EVT1");

      await vi.advanceTimersByTimeAsync(5_000);
      expect(received).toEqual(["reset_decks"]);

      await vi.advanceTimersByTimeAsync(5_000);
      expect(received).toEqual(["reset_decks", "restart"]);
    });
  });
});
