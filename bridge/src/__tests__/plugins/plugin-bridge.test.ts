import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { PluginBridge } from "../../plugins/plugin-bridge.js";
import type { DeckLiveEvent } from "../../deck/deck-state.js";
import type { EquipmentSourcePlugin, PluginCapabilities, PluginConnectionEvent } from "../../plugins/plugin-types.js";
import {
  DEFAULT_CONFIG,
  createMockPlugin,
  FULL_CAPABILITIES,
  getDeckStateSnapshot,
  MINIMAL_CAPABILITIES,
} from "../fixtures/plugin-bridge.js";

describe("PluginBridge", () => {
  let plugin: EquipmentSourcePlugin;
  let bridge: PluginBridge;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(async () => {
    if (bridge?.isRunning) await bridge.stop();
    vi.useRealTimers();
  });

  describe("Lifecycle", () => {
    it("starts and stops the plugin", async () => {
      plugin = createMockPlugin();
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);

      expect(bridge.isRunning).toBe(false);
      await bridge.start();
      expect(bridge.isRunning).toBe(true);
      expect(plugin.isRunning).toBe(true);

      await bridge.stop();
      expect(bridge.isRunning).toBe(false);
    });

    it("throws when starting an already-running bridge", async () => {
      plugin = createMockPlugin();
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();
      await expect(bridge.start()).rejects.toThrow("already running");
    });

    it("cleans up on plugin start failure", async () => {
      plugin = createMockPlugin();
      plugin.start = () => Promise.reject(new Error("Connection failed"));
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);

      await expect(bridge.start()).rejects.toThrow("Connection failed");
      expect(bridge.isRunning).toBe(false);
    });

    it("stop is idempotent when not running", async () => {
      plugin = createMockPlugin();
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.stop(); // Should not throw
    });

    it("exposes plugin info and capabilities", async () => {
      plugin = createMockPlugin();
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      expect(bridge.pluginInfo.id).toBe("mock");
      expect(bridge.pluginCapabilities).toEqual(FULL_CAPABILITIES);
    });
  });

  describe("Full-capability plugin (StageLinQ-like)", () => {
    beforeEach(async () => {
      plugin = createMockPlugin(FULL_CAPABILITIES);
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();
    });

    it("forwards track events to DeckStateManager", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Test Song", artist: "Test Artist" },
      });

      const state = getDeckStateSnapshot(bridge, "1A");
      expect(state.state).toBe("LOADED");
      expect(state.track?.title).toBe("Test Song");
    });

    it("returns isolated deck snapshots that cannot mutate bridge state", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Snapshot Track", artist: "Snapshot Artist", album: "Album" },
      });

      // Regression for baseline 57cfcdc6867f: status consumers must not receive mutable manager state.
      const snapshot = bridge.getDeckStatusSnapshot();
      const mutableSnapshot = snapshot as unknown as {
        deckStates: Array<{ track: { title: string; artist: string; album?: string } | null }>;
      };
      const deckTrack = mutableSnapshot.deckStates[0].track;
      if (!deckTrack) throw new Error("Expected tracked deck metadata");
      deckTrack.title = "Changed by consumer";
      deckTrack.album = "Changed album";
      mutableSnapshot.deckStates.pop();

      expect(bridge.getDeckStatusSnapshot()).toMatchObject({
        deckCount: 1,
        deckStates: [
          { deckId: "1A", track: { title: "Snapshot Track", artist: "Snapshot Artist", album: "Album" } },
        ],
      });
    });

    it("forwards play state events", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Test Song", artist: "Test Artist" },
      });
      plugin.emit("playState", { deckId: "1A", isPlaying: true });

      const state = getDeckStateSnapshot(bridge, "1A");
      expect(state.isPlaying).toBe(true);
      expect(state.state).toBe("CUEING");
    });

    it("forwards fader events", () => {
      plugin.emit("fader", { deckId: "1A", level: 0.75 });

      const state = getDeckStateSnapshot(bridge, "1A");
      expect(state.faderLevel).toBe(0.75);
    });

    it("forwards master deck events", () => {
      plugin.emit("masterDeck", { deckId: "2B" });

      const state = getDeckStateSnapshot(bridge, "2B");
      expect(state.isMaster).toBe(true);
    });

    it("emits deckLive when track reaches threshold", () => {
      const liveEvents: DeckLiveEvent[] = [];
      bridge.on("deckLive", (e: DeckLiveEvent) => liveEvents.push(e));

      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Live Track", artist: "DJ" },
      });
      plugin.emit("playState", { deckId: "1A", isPlaying: true });

      // Advance past threshold
      vi.advanceTimersByTime(16_000);

      expect(liveEvents).toHaveLength(1);
      expect(liveEvents[0].track.title).toBe("Live Track");
      expect(liveEvents[0].deckId).toBe("1A");
    });

    it("forwards connection events from plugin", () => {
      const connections: PluginConnectionEvent[] = [];
      bridge.on("connection", (e: PluginConnectionEvent) =>
        connections.push(e)
      );

      plugin.emit("connection", {
        connected: true,
        deviceName: "SC6000",
      });

      expect(connections).toHaveLength(1);
      expect(connections[0].connected).toBe(true);
      expect(connections[0].deviceName).toBe("SC6000");
    });

    it("forwards ready events from plugin", () => {
      const readyFn = vi.fn();
      bridge.on("ready", readyFn);
      plugin.emit("ready");
      expect(readyFn).toHaveBeenCalledOnce();
    });

    it("forwards plugin log messages with prefix", () => {
      const logs: string[] = [];
      bridge.on("log", (m: string) => logs.push(m));

      plugin.emit("log", "Device found");

      expect(logs.some((m) => m.includes("[mock]") && m.includes("Device found"))).toBe(true);
    });

    it("forwards plugin errors", () => {
      const errors: Error[] = [];
      bridge.on("error", (e: Error) => errors.push(e));

      plugin.emit("error", new Error("Network timeout"));

      expect(errors).toHaveLength(1);
      expect(errors[0].message).toBe("Network timeout");
    });

    it("handles track unload (null track)", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Song", artist: "Artist" },
      });
      plugin.emit("track", { deckId: "1A", track: null });

      const state = getDeckStateSnapshot(bridge, "1A");
      expect(state.state).toBe("EMPTY");
      expect(state.track).toBeNull();
    });
  });

  describe("Minimal-capability plugin (Traktor-like)", () => {
    beforeEach(async () => {
      plugin = createMockPlugin(MINIMAL_CAPABILITIES);
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();
    });

    it("assigns virtual deck ID for single-deck plugins", () => {
      plugin.emit("track", {
        deckId: "anything",
        track: { title: "Song", artist: "Artist" },
      });

      // Should be mapped to virtual deck "1"
      const state = getDeckStateSnapshot(bridge, "1");
      expect(state.track?.title).toBe("Song");
    });

    it("synthesizes play state when track is loaded", () => {
      plugin.emit("track", {
        deckId: "1",
        track: { title: "Song", artist: "Artist" },
      });

      const state = getDeckStateSnapshot(bridge, "1");
      expect(state.isPlaying).toBe(true);
      expect(state.state).toBe("CUEING");
    });

    it("does NOT synthesize play state for track unload", () => {
      plugin.emit("track", {
        deckId: "1",
        track: { title: "Song", artist: "Artist" },
      });
      plugin.emit("track", { deckId: "1", track: null });

      const state = getDeckStateSnapshot(bridge, "1");
      expect(state.state).toBe("EMPTY");
      expect(state.isPlaying).toBe(false);
    });

    it("emits deckLive after threshold with synthesized play state", () => {
      const liveEvents: DeckLiveEvent[] = [];
      bridge.on("deckLive", (e: DeckLiveEvent) => liveEvents.push(e));

      plugin.emit("track", {
        deckId: "1",
        track: { title: "Broadcast Track", artist: "DJ" },
      });

      vi.advanceTimersByTime(16_000);

      expect(liveEvents).toHaveLength(1);
      expect(liveEvents[0].track.title).toBe("Broadcast Track");
      expect(liveEvents[0].deckId).toBe("1");
    });

    it("handles rapid track changes (new track resets threshold)", () => {
      const liveEvents: DeckLiveEvent[] = [];
      bridge.on("deckLive", (e: DeckLiveEvent) => liveEvents.push(e));

      // First track — play for 10s (not enough)
      plugin.emit("track", {
        deckId: "1",
        track: { title: "Track 1", artist: "DJ" },
      });
      vi.advanceTimersByTime(10_000);

      // New track — resets threshold
      plugin.emit("track", {
        deckId: "1",
        track: { title: "Track 2", artist: "DJ" },
      });
      vi.advanceTimersByTime(10_000);
      expect(liveEvents).toHaveLength(0);

      // Finish threshold for Track 2
      vi.advanceTimersByTime(6_000);
      expect(liveEvents).toHaveLength(1);
      expect(liveEvents[0].track.title).toBe("Track 2");
    });
  });

  describe("Multi-deck no-play-state plugin (Serato-like)", () => {
    const SERATO_CAPABILITIES: PluginCapabilities = {
      multiDeck: true,
      playState: false,
      faderLevel: false,
      masterDeck: false,
      albumMetadata: true,
    };

    beforeEach(async () => {
      plugin = createMockPlugin(SERATO_CAPABILITIES);
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();
    });

    it("preserves original deck IDs (multiDeck is true)", () => {
      plugin.emit("track", {
        deckId: "2",
        track: { title: "Song A", artist: "DJ", album: "Album" },
      });

      const state = getDeckStateSnapshot(bridge, "2");
      expect(state.track?.title).toBe("Song A");
      expect(state.track?.album).toBe("Album");
    });

    it("synthesizes play state on track load", () => {
      plugin.emit("track", {
        deckId: "1",
        track: { title: "Song B", artist: "DJ" },
      });

      const state = getDeckStateSnapshot(bridge, "1");
      expect(state.isPlaying).toBe(true);
    });

    it("tracks multiple decks independently", () => {
      plugin.emit("track", {
        deckId: "1",
        track: { title: "Deck 1 Track", artist: "DJ" },
      });
      plugin.emit("track", {
        deckId: "2",
        track: { title: "Deck 2 Track", artist: "DJ" },
      });

      const state1 = getDeckStateSnapshot(bridge, "1");
      const state2 = getDeckStateSnapshot(bridge, "2");
      expect(state1.track?.title).toBe("Deck 1 Track");
      expect(state2.track?.title).toBe("Deck 2 Track");
    });

    it("emits deckLive for first deck that reaches threshold", () => {
      const liveEvents: DeckLiveEvent[] = [];
      bridge.on("deckLive", (e: DeckLiveEvent) => liveEvents.push(e));

      plugin.emit("track", {
        deckId: "1",
        track: { title: "Track 1", artist: "DJ" },
      });

      vi.advanceTimersByTime(16_000);

      expect(liveEvents).toHaveLength(1);
      expect(liveEvents[0].deckId).toBe("1");
      expect(liveEvents[0].track.title).toBe("Track 1");
    });
  });
});
