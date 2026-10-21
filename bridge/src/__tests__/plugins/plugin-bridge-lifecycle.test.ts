import { EventEmitter } from "node:events";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PluginBridge } from "../../plugins/plugin-bridge.js";
import type { DeckStateManagerConfig } from "../../deck/deck-state.js";
import type { EquipmentSourcePlugin } from "../../plugins/plugin-types.js";

const config: DeckStateManagerConfig = {
  liveThresholdSeconds: 1,
  pauseGraceSeconds: 1,
  nowPlayingPauseSeconds: 1,
  useFaderDetection: false,
  masterDeckPriority: false,
};

function createPlugin(stop: () => Promise<void> = () => Promise.resolve()): EquipmentSourcePlugin {
  const emitter = new EventEmitter() as unknown as EquipmentSourcePlugin;
  Object.assign(emitter, {
    info: { id: "mock", name: "Mock", description: "Lifecycle test plugin" },
    capabilities: {
      multiDeck: true,
      playState: true,
      faderLevel: true,
      masterDeck: true,
      albumMetadata: true,
    },
    configOptions: [],
    start: async () => {},
    stop,
  });
  return emitter;
}

describe("PluginBridge lifecycle", () => {
  afterEach(() => vi.useRealTimers());

  it("recreates deck state after restart", async () => {
    vi.useFakeTimers();
    const plugin = createPlugin();
    const bridge = new PluginBridge(plugin, config);
    const events: unknown[] = [];
    bridge.on("deckLive", (event) => events.push(event));

    await bridge.start();
    plugin.emit("track", { deckId: "1", track: { title: "Before", artist: "Artist" } });
    await bridge.restart();

    expect(bridge.getDeckStatusSnapshot().deckStates).toEqual([]);
    plugin.emit("track", { deckId: "1", track: { title: "After", artist: "Artist" } });
    plugin.emit("playState", { deckId: "1", isPlaying: true });
    expect(events).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(999);
    expect(events).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(events).toHaveLength(1);
    await bridge.stop();
  });

  it("propagates plugin stop failure after cleaning up", async () => {
    const failure = new Error("device shutdown failed");
    const bridge = new PluginBridge(createPlugin(async () => { throw failure; }), config);
    await bridge.start();

    await expect(bridge.stop()).rejects.toBe(failure);
    expect(bridge.isRunning).toBe(false);
    expect(bridge.getDeckStatusSnapshot().deckStates).toEqual([]);
  });

  it("does not activate a startup that finishes after stop was requested", async () => {
    vi.useFakeTimers();
    let finishStart!: () => void;
    let pluginRunning = false;
    const startGate = new Promise<void>((resolve) => { finishStart = resolve; });
    const plugin = createPlugin();
    plugin.start = async () => {
      await startGate;
      pluginRunning = true;
    };
    plugin.stop = () => { pluginRunning = false; return Promise.resolve(); };
    const bridge = new PluginBridge(plugin, config);

    const starting = bridge.start();
    const stopping = bridge.stop();
    plugin.emit("connection", { connected: true });
    expect(vi.getTimerCount()).toBe(0);

    finishStart();
    await expect(starting).rejects.toThrow("stopped while starting");
    await stopping;
    expect(pluginRunning).toBe(false);
    expect(bridge.isRunning).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not reconnect after stop wins a deferred reconnect cleanup", async () => {
    vi.useFakeTimers();
    let finishReconnectCleanup!: () => void;
    let stopCalls = 0;
    const reconnectCleanup = new Promise<void>((resolve) => { finishReconnectCleanup = resolve; });
    const plugin = createPlugin(async () => {
      stopCalls++;
      if (stopCalls === 1) await reconnectCleanup;
    });
    const start = vi.spyOn(plugin, "start");
    const bridge = new PluginBridge(plugin, config);
    await bridge.start();
    start.mockClear();

    const reconnecting = bridge.reconnect();
    await Promise.resolve();
    expect(stopCalls).toBe(1);

    const stopping = bridge.stop();
    finishReconnectCleanup();
    await Promise.all([reconnecting, stopping]);

    // Regression for baseline 57cfcdc6867f: a deferred reconnect cleanup could restart after stop.
    expect(start).not.toHaveBeenCalled();
    expect(bridge.isRunning).toBe(false);
  });

  it("stops a reconnect whose plugin start settles after stop is requested", async () => {
    let finishReconnectStart!: () => void;
    let startCalls = 0;
    let pluginRunning = false;
    const reconnectStart = new Promise<void>((resolve) => { finishReconnectStart = resolve; });
    const plugin = createPlugin(() => {
      pluginRunning = false;
      return Promise.resolve();
    });
    plugin.start = async () => {
      startCalls++;
      if (startCalls === 2) await reconnectStart;
      pluginRunning = true;
    };
    plugin.stop = async () => { pluginRunning = false; };
    const bridge = new PluginBridge(plugin, config);
    await bridge.start();

    const reconnecting = bridge.reconnect();
    await Promise.resolve();
    await Promise.resolve();
    expect(startCalls).toBe(2);

    const stopping = bridge.stop();
    finishReconnectStart();
    await Promise.all([reconnecting, stopping]);

    // Regression for baseline 57cfcdc6867f: a pending reconnect start must be stopped too.
    expect(pluginRunning).toBe(false);
    expect(bridge.isRunning).toBe(false);
  });
});
