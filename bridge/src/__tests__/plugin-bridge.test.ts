/**
 * Tests for PluginBridge — the translation layer between plugins and DeckStateManager.
 *
 * Uses a mock plugin (EventEmitter) to verify event normalization,
 * play-state synthesis for limited-capability plugins, and deck ID mapping.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { EventEmitter } from "events";
import { PluginBridge } from "../plugin-bridge.js";
import type { DeckLiveEvent, DeckStateManagerConfig } from "../deck-state.js";
import type {
  EquipmentSourcePlugin,
  PluginCapabilities,
  PluginConnectionEvent,
} from "../plugin-types.js";

const DEFAULT_CONFIG: DeckStateManagerConfig = {
  liveThresholdSeconds: 15,
  pauseGraceSeconds: 3,
  nowPlayingPauseSeconds: 10,
  useFaderDetection: false,
  masterDeckPriority: false,
};

const FULL_CAPABILITIES: PluginCapabilities = {
  multiDeck: true,
  playState: true,
  faderLevel: true,
  masterDeck: true,
  albumMetadata: true,
};

const MINIMAL_CAPABILITIES: PluginCapabilities = {
  multiDeck: false,
  playState: false,
  faderLevel: false,
  masterDeck: false,
  albumMetadata: false,
};

function createMockPlugin(
  capabilities: PluginCapabilities = FULL_CAPABILITIES
): EquipmentSourcePlugin {
  const emitter = new EventEmitter() as EquipmentSourcePlugin;
  let running = false;
  Object.defineProperty(emitter, "isRunning", { get: () => running });
  Object.assign(emitter, {
    info: { id: "mock", name: "Mock Plugin", description: "Test" },
    capabilities,
    configOptions: [],
    start: async () => {
      running = true;
    },
    stop: async () => {
      running = false;
    },
  });
  return emitter;
}

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
      (plugin as unknown as Record<string, unknown>).start = async () => {
        throw new Error("Connection failed");
      };
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

      const state = bridge.manager.getDeckState("1A");
      expect(state.state).toBe("LOADED");
      expect(state.track?.title).toBe("Test Song");
    });

    it("forwards play state events", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Test Song", artist: "Test Artist" },
      });
      plugin.emit("playState", { deckId: "1A", isPlaying: true });

      const state = bridge.manager.getDeckState("1A");
      expect(state.isPlaying).toBe(true);
      expect(state.state).toBe("CUEING");
    });

    it("forwards fader events", () => {
      plugin.emit("fader", { deckId: "1A", level: 0.75 });

      const state = bridge.manager.getDeckState("1A");
      expect(state.faderLevel).toBe(0.75);
    });

    it("forwards master deck events", () => {
      plugin.emit("masterDeck", { deckId: "2B" });

      const state = bridge.manager.getDeckState("2B");
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

      const state = bridge.manager.getDeckState("1A");
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
      const state = bridge.manager.getDeckState("1");
      expect(state.track?.title).toBe("Song");
    });

    it("synthesizes play state when track is loaded", () => {
      plugin.emit("track", {
        deckId: "1",
        track: { title: "Song", artist: "Artist" },
      });

      const state = bridge.manager.getDeckState("1");
      expect(state.isPlaying).toBe(true);
      expect(state.state).toBe("CUEING");
    });

    it("does NOT synthesize play state for track unload", () => {
      plugin.emit("track", {
        deckId: "1",
        track: { title: "Song", artist: "Artist" },
      });
      plugin.emit("track", { deckId: "1", track: null });

      const state = bridge.manager.getDeckState("1");
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

      const state = bridge.manager.getDeckState("2");
      expect(state.track?.title).toBe("Song A");
      expect(state.track?.album).toBe("Album");
    });

    it("synthesizes play state on track load", () => {
      plugin.emit("track", {
        deckId: "1",
        track: { title: "Song B", artist: "DJ" },
      });

      const state = bridge.manager.getDeckState("1");
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

      const state1 = bridge.manager.getDeckState("1");
      const state2 = bridge.manager.getDeckState("2");
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

  describe("Log throttling", () => {
    beforeEach(async () => {
      plugin = createMockPlugin(FULL_CAPABILITIES);
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();
    });

    it("suppresses duplicate log messages within the dedup window", () => {
      const logs: string[] = [];
      bridge.on("log", (m: string) => logs.push(m));

      plugin.emit("log", "Discovery: 192.168.1.71 (IGNORED)");
      plugin.emit("log", "Discovery: 192.168.1.71 (IGNORED)");
      plugin.emit("log", "Discovery: 192.168.1.71 (IGNORED)");

      expect(logs.filter((m) => m.includes("IGNORED"))).toHaveLength(1);
    });

    it("allows the same message again after the dedup window expires", () => {
      const logs: string[] = [];
      bridge.on("log", (m: string) => logs.push(m));

      plugin.emit("log", "Repeated message");
      expect(logs.filter((m) => m.includes("Repeated"))).toHaveLength(1);

      // Advance past the 60s dedup window
      vi.advanceTimersByTime(61_000);

      plugin.emit("log", "Repeated message");
      expect(logs.filter((m) => m.includes("Repeated"))).toHaveLength(2);
    });

    it("allows different messages through independently", () => {
      const logs: string[] = [];
      bridge.on("log", (m: string) => logs.push(m));

      plugin.emit("log", "Message A");
      plugin.emit("log", "Message B");
      plugin.emit("log", "Message A"); // suppressed
      plugin.emit("log", "Message C");

      expect(logs).toHaveLength(3);
    });
  });

  describe("Track deduplication", () => {
    beforeEach(async () => {
      plugin = createMockPlugin(FULL_CAPABILITIES);
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();
    });

    it("ignores same track re-emitted on the same deck (stays PLAYING)", () => {
      // Load and play a track past threshold
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "New Order" },
      });
      plugin.emit("playState", { deckId: "1A", isPlaying: true });
      vi.advanceTimersByTime(16_000);

      const stateBefore = bridge.manager.getDeckState("1A");
      expect(stateBefore.state).toBe("PLAYING");

      // Re-emit the same track (StageLinQ play-state change re-emission)
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "New Order" },
      });

      const stateAfter = bridge.manager.getDeckState("1A");
      expect(stateAfter.state).toBe("PLAYING"); // NOT reset to LOADED
    });

    it("accepts different title on same deck (normal LOADED reset)", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "New Order" },
      });
      plugin.emit("playState", { deckId: "1A", isPlaying: true });
      vi.advanceTimersByTime(16_000);

      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Temptation", artist: "New Order" },
      });

      const state = bridge.manager.getDeckState("1A");
      expect(state.state).toBe("LOADED");
      expect(state.track?.title).toBe("Temptation");
    });

    it("accepts different artist on same deck (normal LOADED reset)", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "New Order" },
      });
      plugin.emit("playState", { deckId: "1A", isPlaying: true });
      vi.advanceTimersByTime(16_000);

      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "Orgy" },
      });

      const state = bridge.manager.getDeckState("1A");
      expect(state.state).toBe("LOADED");
    });

    it("accepts same track on different decks", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "New Order" },
      });
      plugin.emit("playState", { deckId: "1A", isPlaying: true });
      vi.advanceTimersByTime(16_000);

      // Same track on deck 2B should be accepted
      plugin.emit("track", {
        deckId: "2B",
        track: { title: "Blue Monday", artist: "New Order" },
      });

      const state2B = bridge.manager.getDeckState("2B");
      expect(state2B.state).toBe("LOADED");
      expect(state2B.track?.title).toBe("Blue Monday");
    });

    it("accepts null track (unload) even when track is loaded", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "New Order" },
      });

      plugin.emit("track", { deckId: "1A", track: null });

      const state = bridge.manager.getDeckState("1A");
      expect(state.state).toBe("EMPTY");
    });

    it("deduplicates case-insensitively with trimmed whitespace", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "New Order" },
      });
      plugin.emit("playState", { deckId: "1A", isPlaying: true });
      vi.advanceTimersByTime(16_000);

      // Same track with different casing and whitespace
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "  BLUE MONDAY  ", artist: "  new order  " },
      });

      const state = bridge.manager.getDeckState("1A");
      expect(state.state).toBe("PLAYING"); // NOT reset to LOADED
    });
  });

  describe("Bridge heartbeat", () => {
    beforeEach(async () => {
      plugin = createMockPlugin(FULL_CAPABILITIES);
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();
    });

    it("emits heartbeat event every 2 minutes after device connects", () => {
      const heartbeats: unknown[] = [];
      bridge.on("heartbeat", () => heartbeats.push(true));

      plugin.emit("connection", { connected: true, deviceName: "SC6000" });

      // No heartbeat immediately
      expect(heartbeats).toHaveLength(0);

      // After 2 minutes
      vi.advanceTimersByTime(120_000);
      expect(heartbeats).toHaveLength(1);

      // After 4 minutes
      vi.advanceTimersByTime(120_000);
      expect(heartbeats).toHaveLength(2);
    });

    it("stops heartbeat on disconnect", () => {
      const heartbeats: unknown[] = [];
      bridge.on("heartbeat", () => heartbeats.push(true));

      plugin.emit("connection", { connected: true, deviceName: "SC6000" });
      vi.advanceTimersByTime(120_000);
      expect(heartbeats).toHaveLength(1);

      plugin.emit("connection", { connected: false });
      vi.advanceTimersByTime(240_000);
      expect(heartbeats).toHaveLength(1); // No more heartbeats
    });

    it("stops heartbeat on bridge.stop()", async () => {
      const heartbeats: unknown[] = [];
      bridge.on("heartbeat", () => heartbeats.push(true));

      plugin.emit("connection", { connected: true, deviceName: "SC6000" });

      await bridge.stop();
      vi.advanceTimersByTime(240_000);
      expect(heartbeats).toHaveLength(0);
    });

    it("restarts heartbeat on reconnect", () => {
      const heartbeats: unknown[] = [];
      bridge.on("heartbeat", () => heartbeats.push(true));

      // Connect, wait 1 minute, disconnect
      plugin.emit("connection", { connected: true, deviceName: "SC6000" });
      vi.advanceTimersByTime(60_000);
      plugin.emit("connection", { connected: false });

      // Wait — should not get heartbeat from old timer
      vi.advanceTimersByTime(120_000);
      expect(heartbeats).toHaveLength(0);

      // Reconnect
      plugin.emit("connection", { connected: true, deviceName: "SC6000" });
      vi.advanceTimersByTime(120_000);
      expect(heartbeats).toHaveLength(1);
    });
  });

  describe("Authoritative clear on disconnect", () => {
    beforeEach(async () => {
      plugin = createMockPlugin(FULL_CAPABILITIES);
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();
    });

    it("emits clearNowPlaying on device disconnect", () => {
      const clears: unknown[] = [];
      bridge.on("clearNowPlaying", () => clears.push(true));

      plugin.emit("connection", { connected: true, deviceName: "SC6000" });
      plugin.emit("connection", { connected: false });

      expect(clears).toHaveLength(1);
    });

    it("emits clearNowPlaying on bridge.stop()", async () => {
      const clears: unknown[] = [];
      bridge.on("clearNowPlaying", () => clears.push(true));

      await bridge.stop();

      expect(clears).toHaveLength(1);
    });

    it("does not emit clearNowPlaying on connect", () => {
      const clears: unknown[] = [];
      bridge.on("clearNowPlaying", () => clears.push(true));

      plugin.emit("connection", { connected: true, deviceName: "SC6000" });

      expect(clears).toHaveLength(0);
    });

    it("emits clearNowPlaying when last deck ends with no candidate", () => {
      const clears: unknown[] = [];
      bridge.on("clearNowPlaying", () => clears.push(true));

      // Load track on deck, play it past threshold, then stop it
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Song", artist: "Artist" },
      });
      plugin.emit("playState", { deckId: "1A", isPlaying: true });
      vi.advanceTimersByTime(15000); // past liveThresholdSeconds

      plugin.emit("playState", { deckId: "1A", isPlaying: false });
      vi.advanceTimersByTime(3000); // past pauseGraceSeconds

      expect(clears).toHaveLength(1);
    });
  });

  describe("DeckStateManager log forwarding", () => {
    it("forwards DeckStateManager logs", async () => {
      plugin = createMockPlugin(FULL_CAPABILITIES);
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      const logs: string[] = [];
      bridge.on("log", (m: string) => logs.push(m));

      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Song", artist: "Artist" },
      });

      // DeckStateManager emits log messages on track load
      expect(logs.some((m) => m.includes("Track loaded"))).toBe(true);
    });
  });

  describe("Auto-reconnect", () => {
    it("schedules reconnect after disconnect when previously connected", async () => {
      plugin = createMockPlugin();
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      const logs: string[] = [];
      bridge.on("log", (msg: string) => logs.push(msg));

      // Simulate connection then disconnection
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });

      expect(logs.some((m) => m.includes("reconnecting in 2s"))).toBe(true);
    });

    it("does NOT schedule reconnect if never connected", async () => {
      plugin = createMockPlugin();
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      const logs: string[] = [];
      bridge.on("log", (msg: string) => logs.push(msg));

      // Disconnect without prior connection
      plugin.emit("connection", { connected: false });

      expect(logs.some((m) => m.includes("reconnecting"))).toBe(false);
    });

    it("attempts reconnect after backoff delay", async () => {
      plugin = createMockPlugin();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const startSpy = vi.spyOn(plugin as any, "start");
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      // Reset spy to only track reconnect calls
      startSpy.mockClear();

      // Connect then disconnect
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });

      // Before backoff expires: no reconnect
      vi.advanceTimersByTime(1999);
      expect(startSpy).not.toHaveBeenCalled();

      // After 2s backoff: reconnect attempted
      await vi.advanceTimersByTimeAsync(1);
      expect(startSpy).toHaveBeenCalledOnce();
    });

    it("uses exponential backoff on consecutive failures", async () => {
      plugin = createMockPlugin();
      let startCallCount = 0;
      (plugin as unknown as Record<string, unknown>).start = async () => {
        startCallCount++;
        if (startCallCount > 1) {
          throw new Error("Connection failed");
        }
      };
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      const logs: string[] = [];
      bridge.on("log", (msg: string) => logs.push(msg));

      // Connect then disconnect (triggers reconnect)
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });

      // First attempt after 2s — fails
      await vi.advanceTimersByTimeAsync(2000);
      expect(logs.some((m) => m.includes("Reconnect failed"))).toBe(true);

      // Second attempt scheduled after 4s
      expect(logs.some((m) => m.includes("reconnecting in 4s"))).toBe(true);
    });

    it("caps backoff at 30 seconds", async () => {
      plugin = createMockPlugin();
      let startCallCount = 0;
      (plugin as unknown as Record<string, unknown>).start = async () => {
        startCallCount++;
        if (startCallCount > 1) throw new Error("fail");
      };
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      const logs: string[] = [];
      bridge.on("log", (msg: string) => logs.push(msg));

      // Connect then disconnect
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });

      // Advance through several reconnect cycles: 2s, 4s, 8s, 16s, 30s (capped)
      for (const expected of [2, 4, 8, 16, 30]) {
        expect(logs.some((m) => m.includes(`reconnecting in ${expected}s`))).toBe(true);
        await vi.advanceTimersByTimeAsync(expected * 1000);
      }
    });

    it("resets backoff on successful reconnection", async () => {
      plugin = createMockPlugin();
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      const logs: string[] = [];
      bridge.on("log", (msg: string) => logs.push(msg));

      // First cycle: connect → disconnect → reconnect succeeds
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });
      await vi.advanceTimersByTimeAsync(2000); // 2s backoff
      expect(logs.some((m) => m.includes("Reconnected to Mock Plugin successfully"))).toBe(true);

      // Clear logs
      logs.length = 0;

      // Second cycle: disconnect again → backoff should reset to 2s (not 4s)
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });
      expect(logs.some((m) => m.includes("reconnecting in 2s"))).toBe(true);
    });

    it("resets deck state on reconnect", async () => {
      plugin = createMockPlugin();
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      // Load a track on deck 1
      plugin.emit("track", { deckId: "1", track: { title: "Old Song", artist: "Old Artist" } });
      expect(bridge.manager.getDeckState("1").track?.title).toBe("Old Song");

      // Disconnect → reconnect
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });
      await vi.advanceTimersByTimeAsync(2000);

      // After reconnect, deck state should be cleared
      expect(bridge.manager.getDeckIds()).toHaveLength(0);
    });

    it("cancels reconnect on stop", async () => {
      plugin = createMockPlugin();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const startSpy = vi.spyOn(plugin as any, "start");
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();
      startSpy.mockClear();

      // Connect then disconnect (schedules reconnect)
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });

      // Stop before backoff expires
      await bridge.stop();

      // Advance past the reconnect time
      await vi.advanceTimersByTimeAsync(5000);
      expect(startSpy).not.toHaveBeenCalled();
    });

    it("does not schedule duplicate reconnects on multiple disconnect events", async () => {
      plugin = createMockPlugin();
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      const logs: string[] = [];
      bridge.on("log", (msg: string) => logs.push(msg));

      // Connect then disconnect twice
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });
      plugin.emit("connection", { connected: false });

      // Should only see one "reconnecting" message (second is ignored because timer is pending)
      const reconnectLogs = logs.filter((m) => m.includes("reconnecting in"));
      expect(reconnectLogs).toHaveLength(1);
    });
  });
});
