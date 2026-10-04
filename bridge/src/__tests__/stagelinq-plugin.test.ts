/**
 * Tests for StageLinQ Plugin
 *
 * Mocks the stagelinq library to test plugin lifecycle, device
 * events, now-playing handling, state changes, and logger forwarding.
 */
import { EventEmitter } from "events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StageLinqOptions } from "stagelinq";

import type {
  PluginConnectionEvent,
  PluginFaderEvent,
  PluginMasterDeckEvent,
  PluginPlayStateEvent,
  PluginTrackEvent,
} from "../plugin-types.js";

// --- Mock setup ---

const mockDevices = new EventEmitter();
const noopLogger = {
  trace: vi.fn(),
  debug: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
};

const mockStageLinq = {
  options: null as StageLinqOptions | null,
  devices: mockDevices,
  get logger() {
    return this.options?.logger ?? noopLogger;
  },
  connect: vi.fn().mockResolvedValue(undefined),
  disconnect: vi.fn().mockResolvedValue(undefined),
};

vi.mock("stagelinq", () => ({
  StageLinq: mockStageLinq,
}));

// Import AFTER mock setup
const { StageLinqPlugin } = await import("../plugins/stagelinq-plugin.js");

describe("StageLinqPlugin", () => {
  let plugin: InstanceType<typeof StageLinqPlugin>;

  beforeEach(() => {
    plugin = new StageLinqPlugin();
    vi.clearAllMocks();
    mockDevices.removeAllListeners();
    mockStageLinq.options = null;
  });

  afterEach(async () => {
    if (plugin?.isRunning) {
      await plugin.stop();
    }
  });

  describe("metadata", () => {
    it("has correct plugin info", () => {
      expect(plugin.info.id).toBe("stagelinq");
      expect(plugin.info.name).toBe("Denon StageLinQ");
      expect(plugin.info.description).toContain("StageLinQ");
    });

    it("declares all capabilities", () => {
      expect(plugin.capabilities).toEqual({
        multiDeck: true,
        playState: true,
        faderLevel: true,
        masterDeck: true,
        albumMetadata: true,
      });
    });

    it("has no config options", () => {
      expect(plugin.configOptions).toEqual([]);
    });
  });

  describe("lifecycle", () => {
    it("starts and stops cleanly", async () => {
      expect(plugin.isRunning).toBe(false);

      await plugin.start();
      expect(plugin.isRunning).toBe(true);

      await plugin.stop();
      expect(plugin.isRunning).toBe(false);
    });

    it("sets StageLinq options and calls connect on start", async () => {
      await plugin.start();

      expect(mockStageLinq.options).toMatchObject({
        downloadDbSources: false,
        enableFileTranfer: true,
      });
      expect(mockStageLinq.connect).toHaveBeenCalled();
    });

    it("throws when starting an already-running plugin", async () => {
      await plugin.start();
      await expect(plugin.start()).rejects.toThrow("already running");
    });

    it("stop is idempotent when not running", async () => {
      await plugin.stop(); // Should not throw
    });

    it("calls disconnect on stop", async () => {
      await plugin.start();
      await plugin.stop();

      expect(mockStageLinq.disconnect).toHaveBeenCalled();
    });

    it("handles disconnect failure gracefully", async () => {
      mockStageLinq.disconnect.mockRejectedValueOnce(new Error("socket error"));

      await plugin.start();
      await plugin.stop(); // Should not throw
    });
  });

  describe("nowPlaying events", () => {
    it("emits track event with title and artist", async () => {
      const tracks: PluginTrackEvent[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

      await plugin.start();

      mockDevices.emit("nowPlaying", {
        deck: "2",
        title: "One More Time",
        artist: "Daft Punk",
      });

      expect(tracks).toHaveLength(1);
      expect(tracks[0]).toEqual({
        deckId: "2",
        track: {
          title: "One More Time",
          artist: "Daft Punk",
          album: undefined,
        },
      });
    });

    it("passes album through when present", async () => {
      const tracks: PluginTrackEvent[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

      await plugin.start();

      mockDevices.emit("nowPlaying", {
        deck: "1",
        title: "Around The World",
        artist: "Daft Punk",
        album: "Homework",
      });

      expect(tracks[0].track?.album).toBe("Homework");
    });

    it("emits null track when title is empty", async () => {
      const tracks: PluginTrackEvent[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

      await plugin.start();

      mockDevices.emit("nowPlaying", { deck: "1", title: "", artist: "" });

      expect(tracks).toHaveLength(1);
      expect(tracks[0]).toEqual({ deckId: "1", track: null });
    });

    it("defaults deckId to '1' when deck is missing", async () => {
      const tracks: PluginTrackEvent[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

      await plugin.start();

      mockDevices.emit("nowPlaying", {
        title: "Track",
        artist: "Artist",
      });

      expect(tracks[0].deckId).toBe("1");
    });

    it("emits playState from nowPlaying when play field is present", async () => {
      const playStates: PluginPlayStateEvent[] = [];
      plugin.on("playState", (e: PluginPlayStateEvent) => playStates.push(e));

      await plugin.start();

      mockDevices.emit("nowPlaying", {
        deck: "1",
        title: "Track",
        artist: "Artist",
        play: true,
      });

      expect(playStates).toHaveLength(1);
      expect(playStates[0]).toEqual({ deckId: "1", isPlaying: true });
    });

    it("emits playState from nowPlaying when playState field is present", async () => {
      const playStates: PluginPlayStateEvent[] = [];
      plugin.on("playState", (e: PluginPlayStateEvent) => playStates.push(e));

      await plugin.start();

      mockDevices.emit("nowPlaying", {
        deck: "2",
        title: "Track",
        artist: "Artist",
        playState: false,
      });

      expect(playStates).toHaveLength(1);
      expect(playStates[0]).toEqual({ deckId: "2", isPlaying: false });
    });

    it("does not emit playState when neither play nor playState is present", async () => {
      const playStates: PluginPlayStateEvent[] = [];
      plugin.on("playState", (e: PluginPlayStateEvent) => playStates.push(e));

      await plugin.start();

      mockDevices.emit("nowPlaying", {
        deck: "1",
        title: "Track",
        artist: "Artist",
      });

      expect(playStates).toHaveLength(0);
    });
  });

  describe("stateChanged events", () => {
    it("emits playState from stateChanged", async () => {
      const playStates: PluginPlayStateEvent[] = [];
      plugin.on("playState", (e: PluginPlayStateEvent) => playStates.push(e));

      await plugin.start();

      mockDevices.emit("stateChanged", { deck: "1", play: true });

      expect(playStates).toHaveLength(1);
      expect(playStates[0]).toEqual({ deckId: "1", isPlaying: true });
    });

    it("emits fader level from externalMixerVolume", async () => {
      const faders: PluginFaderEvent[] = [];
      plugin.on("fader", (e: PluginFaderEvent) => faders.push(e));

      await plugin.start();

      mockDevices.emit("stateChanged", { deck: "2", externalMixerVolume: 0.75 });

      expect(faders).toHaveLength(1);
      expect(faders[0]).toEqual({ deckId: "2", level: 0.75 });
    });

    it("emits masterDeck from masterStatus", async () => {
      const masters: PluginMasterDeckEvent[] = [];
      plugin.on("masterDeck", (e: PluginMasterDeckEvent) => masters.push(e));

      await plugin.start();

      mockDevices.emit("stateChanged", { deck: "1", masterStatus: true });

      expect(masters).toHaveLength(1);
      expect(masters[0]).toEqual({ deckId: "1" });
    });

    it("does not emit masterDeck when masterStatus is false", async () => {
      const masters: PluginMasterDeckEvent[] = [];
      plugin.on("masterDeck", (e: PluginMasterDeckEvent) => masters.push(e));

      await plugin.start();

      mockDevices.emit("stateChanged", { deck: "1", masterStatus: false });

      expect(masters).toHaveLength(0);
    });

    it("ignores stateChanged without deck", async () => {
      const playStates: PluginPlayStateEvent[] = [];
      const faders: PluginFaderEvent[] = [];
      plugin.on("playState", (e: PluginPlayStateEvent) => playStates.push(e));
      plugin.on("fader", (e: PluginFaderEvent) => faders.push(e));

      await plugin.start();

      mockDevices.emit("stateChanged", { play: true, externalMixerVolume: 0.5 });

      expect(playStates).toHaveLength(0);
      expect(faders).toHaveLength(0);
    });
  });

  describe("connection events", () => {
    it("emits connection event on device connected", async () => {
      const connections: PluginConnectionEvent[] = [];
      plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

      await plugin.start();

      mockDevices.emit("connected", {
        software: { name: "SC6000", version: "3.4.0" },
        address: "192.168.1.10",
      });

      expect(connections).toHaveLength(1);
      expect(connections[0]).toEqual({
        connected: true,
        deviceName: "SC6000",
      });
    });

    it("uses 'Unknown Device' when software name is missing", async () => {
      const connections: PluginConnectionEvent[] = [];
      plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

      await plugin.start();

      mockDevices.emit("connected", {});

      expect(connections[0].deviceName).toBe("Unknown Device");
    });

    it("emits ready event", async () => {
      const readyEvents: void[] = [];
      plugin.on("ready", () => readyEvents.push(undefined));

      await plugin.start();

      mockDevices.emit("ready");

      expect(readyEvents).toHaveLength(1);
    });

    it("emits disconnect event", async () => {
      const connections: PluginConnectionEvent[] = [];
      plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

      await plugin.start();

      mockDevices.emit("disconnect");

      expect(connections).toHaveLength(1);
      expect(connections[0]).toEqual({ connected: false });
    });
  });

  describe("logger forwarding", () => {
    // Regression #690 at a3aa51ae: upstream logger injection replaces EventEmitter.
    it.each(["trace", "debug", "info", "warn", "error"] as const)(
      "forwards %s messages and arguments as log emissions",
      async (level) => {
        const logs: string[] = [];
        plugin.on("log", (message: string) => logs.push(message));
        await plugin.start();
        mockStageLinq.logger[level]("test message", 42);
        expect(logs).toContain(`${level} test message 42`);
      },
    );

    it("stops forwarding messages after stop", async () => {
      await plugin.start();
      const previousLogger = mockStageLinq.logger;
      await plugin.stop();
      const logs: string[] = [];
      // Attach after stop so removeAllListeners cannot hide continued emissions.
      plugin.on("log", (message: string) => logs.push(message));
      previousLogger.info("late message");
      expect(logs).toEqual([]);
    });

    it("only forwards the current run after restart", async () => {
      await plugin.start();
      const previousLogger = mockStageLinq.logger;
      await plugin.stop();
      await plugin.start();
      const logs: string[] = [];
      plugin.on("log", (message: string) => logs.push(message));
      previousLogger.warn("previous run");
      mockStageLinq.logger.info("current run");
      expect(logs).toEqual(["info current run"]);
    });
  });
});
