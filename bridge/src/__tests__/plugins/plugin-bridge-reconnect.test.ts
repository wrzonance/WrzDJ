import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { PluginBridge } from "../../plugins/plugin-bridge.js";
import type { DeckLiveEvent } from "../../deck/deck-state.js";
import type { EquipmentSourcePlugin, PluginConnectionEvent } from "../../plugins/plugin-types.js";
import { DEFAULT_CONFIG, createMockPlugin, getDeckStateSnapshot } from "../fixtures/plugin-bridge.js";

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
      const startSpy = vi.spyOn(plugin, "start");
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
      plugin.start = () => {
        startCallCount++;
        return startCallCount > 1 ? Promise.reject(new Error("Connection failed")) : Promise.resolve();
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
      plugin.start = () => {
        startCallCount++;
        return startCallCount > 1 ? Promise.reject(new Error("fail")) : Promise.resolve();
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
      let failNext = false;
      const originalStart = plugin.start.bind(plugin);
      plugin.start = (config?: Record<string, unknown>) => {
        if (failNext) {
          failNext = false;
          return Promise.reject(new Error("Connection failed"));
        }
        return originalStart(config);
      };
      bridge = new PluginBridge(plugin, DEFAULT_CONFIG);
      await bridge.start();

      const logs: string[] = [];
      bridge.on("log", (msg: string) => logs.push(msg));

      // First cycle: connect → disconnect → first attempt fails, so backoff grows to 4s
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });
      failNext = true;
      await vi.advanceTimersByTimeAsync(2000); // attempt 1 (2s) fails
      expect(logs.some((m) => m.includes("Reconnect failed"))).toBe(true);
      expect(logs.some((m) => m.includes("reconnecting in 4s"))).toBe(true);

      // Attempt 2 (4s) succeeds
      await vi.advanceTimersByTimeAsync(4000);
      expect(logs.some((m) => m.includes("Reconnected to Mock Plugin successfully"))).toBe(true);

      // Clear logs
      logs.length = 0;

      // Second cycle: disconnect again → backoff must be back at 2s, not 8s
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
      expect(getDeckStateSnapshot(bridge, "1").track?.title).toBe("Old Song");

      // Disconnect → reconnect
      plugin.emit("connection", { connected: true, deviceName: "CDJ" });
      plugin.emit("connection", { connected: false });
      await vi.advanceTimersByTimeAsync(2000);

      // After reconnect, deck state should be cleared
      expect(bridge.getDeckStatusSnapshot().deckCount).toBe(0);
    });

    it("cancels reconnect on stop", async () => {
      plugin = createMockPlugin();
      const startSpy = vi.spyOn(plugin, "start");
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
