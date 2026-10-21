import { EventEmitter } from "node:events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BridgeRuntime } from "../../runtime/bridge-runtime.js";
import { loadConfig } from "../../runtime/config.js";
import type { EquipmentSourcePlugin } from "../../plugins/plugin-types.js";

class TestPlugin extends EventEmitter implements EquipmentSourcePlugin {
  readonly info = { id: "test", name: "Test equipment", description: "Test" };
  readonly capabilities = { multiDeck: true, playState: true, faderLevel: false, masterDeck: false, albumMetadata: true };
  readonly configOptions = [];
  isRunning = false;
  start = vi.fn(async () => { this.isRunning = true; });
  stop = vi.fn(async () => { this.isRunning = false; });
}

describe("BridgeRuntime lifecycle", () => {
  let runtime: BridgeRuntime;
  let plugin: TestPlugin;
  let fetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    plugin = new TestPlugin();
    fetch = vi.fn().mockImplementation(async () => new Response("", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    runtime = new BridgeRuntime(loadConfig({ WRZDJ_BRIDGE_API_KEY: "key", WRZDJ_EVENT_CODE: "TEST" }), plugin);
  });

  afterEach(async () => {
    await runtime.stop().catch(() => {});
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("sends an initial handshake and cleans up once on repeated shutdown", async () => {
    await runtime.start();
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/bridge/status"), expect.objectContaining({
      body: expect.stringContaining('"connected":true'),
    }));
    await Promise.all([runtime.stop(), runtime.stop()]);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/nowplaying/TEST"), expect.objectContaining({ method: "DELETE" }));
    expect(plugin.stop).toHaveBeenCalledOnce();
    expect(plugin.isRunning).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  // Regression: 57cfcdc6867f could post startup-online after shutdown-offline.
  it("waits for the startup status post before sending shutdown status", async () => {
    const order: string[] = [];
    let finishOnline!: (response: Response) => void;
    fetch.mockImplementation((url: string, options: RequestInit) => {
      const body = options.body ? JSON.parse(String(options.body)) as { connected?: boolean } : {};
      if (url.includes("/bridge/status") && body.connected === true) {
        order.push("online-start");
        return new Promise<Response>((resolve) => {
          finishOnline = (response) => {
            order.push("online-finished");
            resolve(response);
          };
        });
      }
      order.push(url.includes("/bridge/status") ? "offline-start" : "clear-start");
      return Promise.resolve(new Response("", { status: 200 }));
    });

    const starting = runtime.start();
    await vi.waitFor(() => expect(finishOnline).toBeTypeOf("function"));
    const stopping = runtime.stop();
    await vi.waitFor(() => expect(plugin.stop).toHaveBeenCalledOnce());
    await vi.advanceTimersByTimeAsync(0);

    expect(order).toEqual(["online-start"]);

    finishOnline(new Response("", { status: 200 }));
    await Promise.all([starting, stopping]);

    expect(order).toEqual(["online-start", "online-finished", "clear-start", "offline-start"]);
  });

  it("exposes a live status snapshot and forwards equipment connection events", async () => {
    const statuses: Array<{ running: boolean; pluginId: string; deckCount: number }> = [];
    const connections: Array<{ connected: boolean; deviceName?: string }> = [];
    runtime.on("statusChanged", (status) => statuses.push(status));
    runtime.on("connection", (event) => connections.push(event));

    expect(runtime.getSnapshot().running).toBe(false);
    await runtime.start();
    plugin.emit("connection", { connected: true, deviceName: "Player 1" });

    expect(runtime.getSnapshot()).toMatchObject({ running: true, pluginId: "test", deckCount: 0 });
    expect(connections).toEqual([{ connected: true, deviceName: "Player 1" }]);
    expect(statuses.some((status) => status.running)).toBe(true);

    await runtime.stop();
    expect(runtime.getSnapshot().running).toBe(false);
    expect(statuses.at(-1)?.running).toBe(false);
  });

  // Regression at 57cfcdc6867f: manager logs caused duplicate runtime status notifications.
  it("emits one user-visible status update for a deck-manager log", async () => {
    const statuses = vi.fn();
    const logs: Array<{ message: string; level: string }> = [];
    runtime.on("statusChanged", statuses);
    runtime.on("log", (entry) => logs.push(entry));
    await runtime.start();
    statuses.mockClear();
    logs.length = 0;

    plugin.emit("track", {
      deckId: "1",
      track: { title: "Test track", artist: "Test artist" },
    });

    expect(logs).toEqual([{
      message: 'Deck 1: Track loaded "Test track" by Test artist → LOADED',
      level: "info",
    }]);
    expect(statuses).toHaveBeenCalledOnce();
    expect(statuses).toHaveBeenCalledWith(expect.objectContaining({ deckCount: 1 }));
  });

  it("returns deck snapshots that cannot mutate runtime state", async () => {
    await runtime.start();
    plugin.emit("track", { deckId: "1", track: { title: "Original", artist: "Artist" } });

    const snapshot = runtime.getSnapshot();
    const deck = snapshot.deckStates[0] as { state: string; track: { title: string; artist: string } };
    deck.state = "EMPTY";
    deck.track.title = "Changed";

    expect(runtime.getSnapshot().deckStates[0]).toMatchObject({ state: "LOADED", track: { title: "Original" } });
  });

  it("attempts all final cleanup when plugin stop fails and preserves the stop error", async () => {
    await runtime.start();
    plugin.stop.mockRejectedValueOnce(new Error("plugin stop failed"));

    await expect(runtime.stop()).rejects.toThrow("plugin stop failed");

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/nowplaying/TEST"), expect.objectContaining({ method: "DELETE" }));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/bridge/status"), expect.objectContaining({
      body: expect.stringContaining('"connected":false'),
    }));
    expect(runtime.getSnapshot().running).toBe(false);
  });

  it("does not publish events or start polling when stopped during equipment startup", async () => {
    let finishStart!: () => void;
    plugin.start.mockImplementationOnce(() => new Promise<void>((resolve) => { finishStart = resolve; }));
    const starting = runtime.start();
    await Promise.resolve();
    const stopping = runtime.stop();
    finishStart();
    await expect(starting).rejects.toThrow(/stopped while starting/i);
    await stopping;
    expect(runtime.getSnapshot().running).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    expect(fetch.mock.calls.some(([url]) => String(url).includes("/commands/"))).toBe(false);
  });

  it("removes timers and listeners when equipment startup fails", async () => {
    plugin.start.mockRejectedValueOnce(new Error("equipment unavailable"));
    await expect(runtime.start()).rejects.toThrow("equipment unavailable");
    expect(vi.getTimerCount()).toBe(0);
    expect(plugin.eventNames()).toEqual([]);
  });

  // Regression: 57cfcdc6867f dispatched async lifecycle commands concurrently.
  it("finishes reconnect before starting a queued restart", async () => {
    await runtime.start();
    let release!: () => void;
    const stopped = new Promise<void>((resolve) => { release = resolve; });
    plugin.stop.mockImplementationOnce(() => stopped);
    fetch.mockImplementation(async (url: string) => new Response(
      url.includes("/commands/") ? JSON.stringify({ commands: [
        { command_id: "1", command_type: "reconnect" },
        { command_id: "2", command_type: "restart" },
      ] }) : "", { status: 200 },
    ));
    await vi.advanceTimersByTimeAsync(5000);
    expect(plugin.stop).toHaveBeenCalledOnce();
    expect(plugin.start).toHaveBeenCalledOnce();
    release();
    await vi.advanceTimersByTimeAsync(1);
    expect(plugin.stop).toHaveBeenCalledTimes(2);
    expect(plugin.start).toHaveBeenCalledTimes(3);
  });

  it("reports equipment errors through the logger without an unhandled error event", async () => {
    await runtime.start();
    expect(() => plugin.emit("error", new Error("connection lost"))).not.toThrow();
  });

  it("signals app-configured authentication expiry without reporting the backend unavailable", async () => {
    const expiredRuntime = new BridgeRuntime(
      loadConfig({ WRZDJ_BRIDGE_API_KEY: "key", WRZDJ_EVENT_CODE: "TEST" }),
      plugin,
      { stopOnUnauthorized: true },
    );
    const authenticationError = vi.fn();
    expiredRuntime.on("authenticationError", authenticationError);
    fetch.mockResolvedValueOnce(new Response("", { status: 401 }));

    await expiredRuntime.start();

    expect(authenticationError).toHaveBeenCalledOnce();
    expect(expiredRuntime.getSnapshot().backendReachable).toBe(true);
    expect(expiredRuntime.getSnapshot().circuitBreakerState).toBe("CLOSED");
    await expiredRuntime.stop();
  });

  it("signals authentication expiry from command polling", async () => {
    const expiredRuntime = new BridgeRuntime(
      loadConfig({ WRZDJ_BRIDGE_API_KEY: "key", WRZDJ_EVENT_CODE: "TEST" }),
      plugin,
      { stopOnUnauthorized: true },
    );
    const authenticationError = vi.fn();
    expiredRuntime.on("authenticationError", authenticationError);
    fetch.mockImplementation(async (url: string) => new Response(
      "", { status: url.includes("/commands/") ? 401 : 200 },
    ));

    await expiredRuntime.start();
    await vi.advanceTimersByTimeAsync(5_000);

    expect(authenticationError).toHaveBeenCalledOnce();
    expect(expiredRuntime.getSnapshot().backendReachable).toBe(true);
    expect(expiredRuntime.getSnapshot().circuitBreakerState).toBe("CLOSED");
    await expiredRuntime.stop();
  });

  it("forwards polled ping and transport commands to the app event/log surface", async () => {
    const ping = vi.fn();
    const logs: Array<{ message: string; level: string }> = [];
    runtime.on("ping", ping);
    runtime.on("log", (entry) => logs.push(entry));
    fetch.mockImplementation(async (url: string) => url.includes("/commands/")
      ? new Response(JSON.stringify({ commands: [
        { command_id: "1", command_type: "ping" },
        { command_id: "2", command_type: "setbuilder_transport", payload: { action: "play", title: "A", position_sec: 3 } },
      ] }), { status: 200 })
      : new Response("", { status: 200 }));
    await runtime.start();

    await vi.advanceTimersByTimeAsync(5000);

    expect(ping).toHaveBeenCalledOnce();
    expect(logs.some((entry) => entry.message === 'Setbuilder transport command received: play "A" @ 3.0s')).toBe(true);
  });
});
