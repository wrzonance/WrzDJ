import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { PluginBridge } from "../../plugins/plugin-bridge.js";
import type { DeckLiveEvent } from "../../deck/deck-state.js";
import type { EquipmentSourcePlugin, PluginConnectionEvent } from "../../plugins/plugin-types.js";
import { DEFAULT_CONFIG, createMockPlugin, FULL_CAPABILITIES, getDeckStateSnapshot } from "../fixtures/plugin-bridge.js";

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

      const stateBefore = getDeckStateSnapshot(bridge, "1A");
      expect(stateBefore.state).toBe("PLAYING");

      // Re-emit the same track (StageLinQ play-state change re-emission)
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "New Order" },
      });

      const stateAfter = getDeckStateSnapshot(bridge, "1A");
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

      const state = getDeckStateSnapshot(bridge, "1A");
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

      const state = getDeckStateSnapshot(bridge, "1A");
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

      const state2B = getDeckStateSnapshot(bridge, "2B");
      expect(state2B.state).toBe("LOADED");
      expect(state2B.track?.title).toBe("Blue Monday");
    });

    it("accepts null track (unload) even when track is loaded", () => {
      plugin.emit("track", {
        deckId: "1A",
        track: { title: "Blue Monday", artist: "New Order" },
      });

      plugin.emit("track", { deckId: "1A", track: null });

      const state = getDeckStateSnapshot(bridge, "1A");
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

      const state = getDeckStateSnapshot(bridge, "1A");
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
});
