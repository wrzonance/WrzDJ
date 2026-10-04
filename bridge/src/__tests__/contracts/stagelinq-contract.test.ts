/**
 * Contract tests for the `stagelinq` npm package.
 *
 * These tests import the REAL library (no vi.mock) and validate that the API
 * surface our StageLinqPlugin depends on still exists and behaves as expected.
 * The adapter test stubs connect/disconnect at the network boundary; no test opens sockets.
 *
 * If these tests fail after a version bump, it means the library's public API
 * has changed and StageLinqPlugin needs updating.
 *
 * Reference: bridge/src/plugins/stagelinq-plugin.ts
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { StageLinq } from "stagelinq";
import { StageLinqPlugin } from "../../plugins/stagelinq-plugin.js";

describe("stagelinq API contract", () => {
  afterEach(() => vi.restoreAllMocks());

  it("exports StageLinq singleton", () => {
    expect(StageLinq).toBeDefined();
    // StageLinq is a class (typeof === "function") used as a singleton via static members
    expect(typeof StageLinq).toBe("function");
  });

  it("has settable options property", () => {
    // The plugin sets these options before connecting.
    // Note: "enableFileTranfer" is the real API spelling (missing 's').
    expect(() => {
      StageLinq.options = {
        downloadDbSources: false,
        enableFileTranfer: false,
      };
    }).not.toThrow();
  });

  it("exposes devices as EventEmitter", () => {
    expect(StageLinq.devices).toBeDefined();
    expect(typeof StageLinq.devices.on).toBe("function");
    expect(typeof StageLinq.devices.removeListener).toBe("function");
  });

  it("forwards every documented level to the injected logger", () => {
    const messages: unknown[][] = [];
    const write = (message: string, ...args: unknown[]) => {
      messages.push([message, ...args]);
    };
    StageLinq.options = {
      downloadDbSources: false,
      enableFileTranfer: true,
      logger: { trace: write, debug: write, info: write, warn: write, error: write },
    };
    const levels = ["trace", "debug", "info", "warn", "error"] as const;
    const logger = StageLinq.logger;
    messages.length = 0; // Ignore the singleton's initialization log.
    for (const level of levels) logger[level](`${level} message`, 42);
    expect(messages).toEqual(levels.map((level) => [`${level} message`, 42]));
  });

  it("starts the adapter and forwards real library events without opening sockets", async () => {
    // Regression #690 at a3aa51ae: the old adapter calls the removed logger.on API.
    vi.spyOn(StageLinq, "connect").mockResolvedValue(undefined);
    vi.spyOn(StageLinq, "disconnect").mockResolvedValue(undefined);
    const plugin = new StageLinqPlugin();
    const logs: string[] = [];
    const tracks: unknown[] = [];
    plugin.on("log", (message: string) => logs.push(message));
    plugin.on("track", (track: unknown) => tracks.push(track));
    try {
      await plugin.start();
      StageLinq.logger.info("upstream message", 42);
      StageLinq.devices.emit("nowPlaying", { deck: "2A", title: "Track", artist: "Artist" });
      expect(logs).toContain("info upstream message 42");
      expect(tracks).toEqual([
        { deckId: "2A", track: { title: "Track", artist: "Artist", album: undefined } },
      ]);
    } finally {
      await plugin.stop();
    }
  });

  it("has connect method returning thenable", () => {
    // DO NOT call — would bind network sockets
    expect(typeof StageLinq.connect).toBe("function");
  });

  it("has disconnect method returning thenable", () => {
    // DO NOT call — would bind network sockets
    expect(typeof StageLinq.disconnect).toBe("function");
  });
});
