/**
 * Tests for Pioneer PRO DJ LINK Plugin
 *
 * Mocks the prolink-connect library to test plugin lifecycle, device
 * discovery, CDJ status handling, and track metadata fetching.
 */
import { EventEmitter } from "events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PluginConnectionEvent,
  PluginFaderEvent,
  PluginMasterDeckEvent,
  PluginPlayStateEvent,
  PluginTrackEvent,
} from "../plugin-types.js";

// --- Mock setup ---

const mockDeviceManager = new EventEmitter();
const mockStatusEmitter = new EventEmitter();
const mockDb = {
  getMetadata: vi.fn(),
};

const mockNetwork = {
  deviceManager: mockDeviceManager,
  statusEmitter: mockStatusEmitter,
  db: mockDb,
  autoconfigFromPeers: vi.fn().mockResolvedValue(undefined),
  connect: vi.fn(),
  disconnect: vi.fn().mockReturnValue(() => Promise.resolve(undefined)),
  close: vi.fn().mockResolvedValue(undefined),
};

vi.mock("alphatheta-connect", () => ({
  bringOnline: vi.fn().mockResolvedValue(mockNetwork),
  CDJStatus: {
    PlayState: {
      Empty: 0,
      Loading: 2,
      Playing: 3,
      Looping: 4,
      Paused: 5,
      Cued: 6,
      Cuing: 7,
      PlatterHeld: 8,
      Searching: 9,
      SpunDown: 14,
      Ended: 17,
    },
  },
  DeviceType: {
    CDJ: 1,
    Mixer: 3,
    Rekordbox: 4,
  },
}));

// Import AFTER mock setup
const { PioneerProlinkPlugin } = await import("../plugins/pioneer-prolink-plugin.js");

/** Build a mock CDJ status packet with sensible defaults */
function makeStatus(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    deviceId: 1,
    trackId: 42,
    trackDeviceId: 1,
    trackSlot: 3, // USB
    trackType: 1, // RB
    playState: 3, // Playing
    isOnAir: true,
    isSync: false,
    isMaster: false,
    isEmergencyMode: false,
    trackBPM: 128,
    effectivePitch: 0,
    sliderPitch: 0,
    beatInMeasure: 1,
    beatsUntilCue: null,
    beat: 100,
    packetNum: 1,
    ...overrides,
  };
}

describe("PioneerProlinkPlugin", () => {
  let plugin: InstanceType<typeof PioneerProlinkPlugin>;

  beforeEach(() => {
    plugin = new PioneerProlinkPlugin();
    vi.clearAllMocks();
    mockDeviceManager.removeAllListeners();
    mockStatusEmitter.removeAllListeners();
  });

  afterEach(async () => {
    if (plugin?.isRunning) {
      await plugin.stop();
    }
  });

  describe("metadata", () => {
    it("has correct plugin info", () => {
      expect(plugin.info.id).toBe("pioneer-prolink");
      expect(plugin.info.name).toBe("Pioneer PRO DJ LINK");
      expect(plugin.info.description).toContain("Pioneer DJ");
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

    it("calls bringOnline, autoconfigFromPeers, and connect on start", async () => {
      const { bringOnline } = await import("alphatheta-connect");

      await plugin.start();

      expect(bringOnline).toHaveBeenCalled();
      expect(mockNetwork.autoconfigFromPeers).toHaveBeenCalled();
      expect(mockNetwork.connect).toHaveBeenCalled();
    });

    it("emits ready after start", async () => {
      const readyEvents: void[] = [];
      plugin.on("ready", () => readyEvents.push(undefined));

      await plugin.start();

      expect(readyEvents).toHaveLength(1);
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

      expect(mockNetwork.disconnect).toHaveBeenCalled();
    });

    it("handles disconnect failure gracefully", async () => {
      mockNetwork.disconnect.mockReturnValueOnce(() => Promise.reject(new Error("socket error")));

      await plugin.start();
      await plugin.stop(); // Should not throw
    });

    it("recovers from autoconfigFromPeers failure", async () => {
      mockNetwork.autoconfigFromPeers.mockRejectedValueOnce(new Error("No peers found"));

      await expect(plugin.start()).rejects.toThrow("No peers found");
      expect(plugin.isRunning).toBe(false);

      // Should be able to retry
      mockNetwork.autoconfigFromPeers.mockResolvedValueOnce(undefined);
      await plugin.start();
      expect(plugin.isRunning).toBe(true);
    });
  });

  describe("device events", () => {
    it("emits connection event when CDJ connects", async () => {
      const connections: PluginConnectionEvent[] = [];
      plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

      await plugin.start();

      mockDeviceManager.emit("connected", {
        name: "CDJ-3000",
        id: 1,
        type: 1, // DeviceType.CDJ
        macAddr: new Uint8Array([0, 0, 0, 0, 0, 0]),
        ip: {},
      });

      expect(connections).toHaveLength(1);
      expect(connections[0]).toEqual({
        connected: true,
        deviceName: "CDJ-3000",
      });
    });

    it("emits connection event when CDJ disconnects", async () => {
      const connections: PluginConnectionEvent[] = [];
      plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

      await plugin.start();

      mockDeviceManager.emit("disconnected", {
        name: "CDJ-3000",
        id: 1,
        type: 1, // DeviceType.CDJ
        macAddr: new Uint8Array([0, 0, 0, 0, 0, 0]),
        ip: {},
      });

      expect(connections).toHaveLength(1);
      expect(connections[0]).toEqual({
        connected: false,
        deviceName: "CDJ-3000",
      });
    });

    it("ignores non-CDJ devices (mixers)", async () => {
      const connections: PluginConnectionEvent[] = [];
      plugin.on("connection", (e: PluginConnectionEvent) => connections.push(e));

      await plugin.start();

      mockDeviceManager.emit("connected", {
        name: "DJM-900NXS2",
        id: 33,
        type: 3, // DeviceType.Mixer
        macAddr: new Uint8Array([0, 0, 0, 0, 0, 0]),
        ip: {},
      });

      expect(connections).toHaveLength(0);
    });
  });

  describe("CDJ status events", () => {
    it("emits playState when CDJ is playing", async () => {
      const playStates: PluginPlayStateEvent[] = [];
      plugin.on("playState", (e: PluginPlayStateEvent) => playStates.push(e));

      await plugin.start();
      mockDb.getMetadata.mockResolvedValue(null);

      mockStatusEmitter.emit("status", makeStatus({ playState: 3 }));

      expect(playStates).toHaveLength(1);
      expect(playStates[0]).toEqual({ deckId: "1", isPlaying: true });
    });

    it("emits playState false when CDJ is paused", async () => {
      const playStates: PluginPlayStateEvent[] = [];
      plugin.on("playState", (e: PluginPlayStateEvent) => playStates.push(e));

      await plugin.start();
      mockDb.getMetadata.mockResolvedValue(null);

      mockStatusEmitter.emit("status", makeStatus({ playState: 5 })); // Paused

      expect(playStates).toHaveLength(1);
      expect(playStates[0]).toEqual({ deckId: "1", isPlaying: false });
    });

    it("emits fader level 1.0 when on-air", async () => {
      const faders: PluginFaderEvent[] = [];
      plugin.on("fader", (e: PluginFaderEvent) => faders.push(e));

      await plugin.start();
      mockDb.getMetadata.mockResolvedValue(null);

      mockStatusEmitter.emit("status", makeStatus({ isOnAir: true }));

      expect(faders).toHaveLength(1);
      expect(faders[0]).toEqual({ deckId: "1", level: 1.0 });
    });

    it("emits fader level 0.0 when off-air", async () => {
      const faders: PluginFaderEvent[] = [];
      plugin.on("fader", (e: PluginFaderEvent) => faders.push(e));

      await plugin.start();
      mockDb.getMetadata.mockResolvedValue(null);

      mockStatusEmitter.emit("status", makeStatus({ isOnAir: false }));

      expect(faders).toHaveLength(1);
      expect(faders[0]).toEqual({ deckId: "1", level: 0.0 });
    });

    it("emits masterDeck when CDJ is master", async () => {
      const masters: PluginMasterDeckEvent[] = [];
      plugin.on("masterDeck", (e: PluginMasterDeckEvent) => masters.push(e));

      await plugin.start();
      mockDb.getMetadata.mockResolvedValue(null);

      mockStatusEmitter.emit("status", makeStatus({ isMaster: true }));

      expect(masters).toHaveLength(1);
      expect(masters[0]).toEqual({ deckId: "1" });
    });

    it("does not emit masterDeck when CDJ is not master", async () => {
      const masters: PluginMasterDeckEvent[] = [];
      plugin.on("masterDeck", (e: PluginMasterDeckEvent) => masters.push(e));

      await plugin.start();
      mockDb.getMetadata.mockResolvedValue(null);

      mockStatusEmitter.emit("status", makeStatus({ isMaster: false }));

      expect(masters).toHaveLength(0);
    });

    it("uses deviceId as deckId string", async () => {
      const playStates: PluginPlayStateEvent[] = [];
      plugin.on("playState", (e: PluginPlayStateEvent) => playStates.push(e));

      await plugin.start();
      mockDb.getMetadata.mockResolvedValue(null);

      mockStatusEmitter.emit("status", makeStatus({ deviceId: 3 }));

      expect(playStates[0].deckId).toBe("3");
    });
  });

  describe("track change detection", () => {
    it("emits track event with metadata on track change", async () => {
      const tracks: PluginTrackEvent[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

      mockDb.getMetadata.mockResolvedValue({
        id: 42,
        title: "One More Time",
        artist: { id: 1, name: "Daft Punk" },
        album: { id: 1, name: "Discovery" },
        duration: 320,
        tempo: 122,
        rating: 0,
        comment: "",
        filePath: "/music/track.mp3",
        fileName: "track.mp3",
        beatGrid: null,
        cueAndLoops: null,
        waveformHd: null,
      });

      await plugin.start();
      mockStatusEmitter.emit("status", makeStatus({ trackId: 42 }));

      // Wait for async metadata fetch
      await vi.waitFor(() => expect(tracks).toHaveLength(1));

      expect(tracks[0]).toEqual({
        deckId: "1",
        track: {
          title: "One More Time",
          artist: "Daft Punk",
          album: "Discovery",
        },
      });
    });

    it("does not re-emit for same trackId on same deck", async () => {
      const tracks: PluginTrackEvent[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

      mockDb.getMetadata.mockResolvedValue({
        id: 42,
        title: "Track",
        artist: { id: 1, name: "Artist" },
        album: null,
        duration: 300,
        tempo: 128,
        rating: 0,
        comment: "",
        filePath: "",
        fileName: "",
        beatGrid: null,
        cueAndLoops: null,
        waveformHd: null,
      });

      await plugin.start();

      mockStatusEmitter.emit("status", makeStatus({ trackId: 42, packetNum: 1 }));
      mockStatusEmitter.emit("status", makeStatus({ trackId: 42, packetNum: 2 }));

      await vi.waitFor(() => expect(tracks).toHaveLength(1));

      // Give time for potential second emit
      await new Promise((r) => setTimeout(r, 50));
      expect(tracks).toHaveLength(1);
    });

    it("emits track null when track is unloaded (trackId=0)", async () => {
      const tracks: PluginTrackEvent[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

      mockDb.getMetadata.mockResolvedValue({
        id: 42,
        title: "Track",
        artist: { id: 1, name: "Artist" },
        album: null,
        duration: 300,
        tempo: 128,
        rating: 0,
        comment: "",
        filePath: "",
        fileName: "",
        beatGrid: null,
        cueAndLoops: null,
        waveformHd: null,
      });

      await plugin.start();

      // Load a track first
      mockStatusEmitter.emit("status", makeStatus({ trackId: 42 }));
      await vi.waitFor(() => expect(tracks).toHaveLength(1));

      // Unload
      mockStatusEmitter.emit("status", makeStatus({ trackId: 0 }));

      expect(tracks).toHaveLength(2);
      expect(tracks[1]).toEqual({ deckId: "1", track: null });
    });

    it("handles metadata fetch failure by retrying and emitting partial track", async () => {
      const tracks: PluginTrackEvent[] = [];
      const logs: string[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));
      plugin.on("log", (msg: string) => logs.push(msg));

      mockDb.getMetadata.mockRejectedValue(new Error("Connection refused"));

      await plugin.start();
      mockStatusEmitter.emit("status", makeStatus({ trackId: 99 }));

      // Wait for initial failure
      await vi.waitFor(() => expect(logs.some((l) => l.includes("Failed to fetch"))).toBe(true));
      // Wait for retry (3s delay) and final partial emit
      await vi.waitFor(() => expect(logs.some((l) => l.includes("Metadata unavailable"))).toBe(true), { timeout: 5000 });

      // Should emit a partial track event with "Unknown Track"
      expect(tracks).toHaveLength(1);
      expect(tracks[0]!.track).toEqual({ title: "Unknown Track", artist: "Unknown" });
    });

    it("handles null metadata result by emitting partial track", async () => {
      const tracks: PluginTrackEvent[] = [];
      const logs: string[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));
      plugin.on("log", (msg: string) => logs.push(msg));

      mockDb.getMetadata.mockResolvedValue(null);

      await plugin.start();
      mockStatusEmitter.emit("status", makeStatus({ trackId: 77 }));

      await vi.waitFor(() => expect(logs.some((l) => l.includes("No metadata"))).toBe(true));

      // Now emits a partial track (state machine transitions even without metadata)
      expect(tracks).toHaveLength(1);
      expect(tracks[0]!.track).toEqual({ title: "Unknown Track", artist: "Unknown" });
    });

    it("handles track with no artist or album", async () => {
      const tracks: PluginTrackEvent[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

      mockDb.getMetadata.mockResolvedValue({
        id: 10,
        title: "Unknown Track",
        artist: null,
        album: null,
        duration: 200,
        tempo: 130,
        rating: 0,
        comment: "",
        filePath: "",
        fileName: "",
        beatGrid: null,
        cueAndLoops: null,
        waveformHd: null,
      });

      await plugin.start();
      mockStatusEmitter.emit("status", makeStatus({ trackId: 10 }));

      await vi.waitFor(() => expect(tracks).toHaveLength(1));

      expect(tracks[0].track).toEqual({
        title: "Unknown Track",
        artist: "",
        album: undefined,
      });
    });

    it("passes correct options to getMetadata", async () => {
      mockDb.getMetadata.mockResolvedValue(null);

      await plugin.start();
      mockStatusEmitter.emit(
        "status",
        makeStatus({
          trackId: 55,
          trackDeviceId: 2,
          trackSlot: 2, // SD
          trackType: 1, // RB
        }),
      );

      await vi.waitFor(() => expect(mockDb.getMetadata).toHaveBeenCalled());

      expect(mockDb.getMetadata).toHaveBeenCalledWith({
        deviceId: 2,
        trackSlot: 2,
        trackType: 1,
        trackId: 55,
      });
    });

    it("tracks different decks independently", async () => {
      const tracks: PluginTrackEvent[] = [];
      plugin.on("track", (e: PluginTrackEvent) => tracks.push(e));

      mockDb.getMetadata.mockImplementation(async (opts: { trackId: number }) => ({
        id: opts.trackId,
        title: `Track ${opts.trackId}`,
        artist: { id: 1, name: "Artist" },
        album: null,
        duration: 300,
        tempo: 128,
        rating: 0,
        comment: "",
        filePath: "",
        fileName: "",
        beatGrid: null,
        cueAndLoops: null,
        waveformHd: null,
      }));

      await plugin.start();

      // Deck 1 loads track 42
      mockStatusEmitter.emit("status", makeStatus({ deviceId: 1, trackId: 42 }));
      // Deck 2 loads track 43
      mockStatusEmitter.emit("status", makeStatus({ deviceId: 2, trackId: 43 }));

      await vi.waitFor(() => expect(tracks).toHaveLength(2));

      expect(tracks[0].deckId).toBe("1");
      expect(tracks[0].track?.title).toBe("Track 42");
      expect(tracks[1].deckId).toBe("2");
      expect(tracks[1].track?.title).toBe("Track 43");
    });

    it("times out metadata fetch after 10 seconds", async () => {
      vi.useFakeTimers();
      const logs: string[] = [];
      plugin.on("log", (msg: string) => logs.push(msg));

      // Mock getMetadata to never resolve
      mockDb.getMetadata.mockImplementation(() => new Promise(() => {}));

      await plugin.start();
      mockStatusEmitter.emit("status", makeStatus({ trackId: 99 }));

      // Advance past the 10s timeout
      await vi.advanceTimersByTimeAsync(11_000);

      expect(logs.some((l) => l.includes("timed out"))).toBe(true);
      vi.useRealTimers();
    });
  });

  // Regression #996 at d4c3bbbb: stop() ignored a pending start (a late CDJ revived the plugin)
  // and never closed the UDP sockets (disconnect()() throws on the detached close function).
  describe("stop while starting", () => {
    // Before autoconfig completes the real disconnect() throws; teardown must still close the sockets
    beforeEach(() => {
      mockNetwork.disconnect.mockImplementation(() => {
        throw new Error("Network must be configured");
      });
    });

    afterEach(() => {
      mockNetwork.disconnect.mockReset();
      mockNetwork.disconnect.mockReturnValue(() => Promise.resolve(undefined));
    });

    /** A promise the test settles by hand, to hold start() at a chosen await */
    function deferred<T = void>() {
      let resolve!: (value: T) => void;
      const promise = new Promise<T>((res) => {
        resolve = res;
      });
      return { promise, resolve };
    }

    it("cancels a start that is still waiting for the first CDJ", async () => {
      const firstCdj = deferred();
      mockNetwork.autoconfigFromPeers.mockImplementationOnce(() => firstCdj.promise);
      const onReady = vi.fn();
      plugin.on("ready", onReady);

      const starting = plugin.start();
      await vi.waitFor(() => expect(mockNetwork.autoconfigFromPeers).toHaveBeenCalled());

      await plugin.stop();
      await expect(starting).resolves.toBeUndefined();

      expect(mockNetwork.close).toHaveBeenCalledTimes(1);
      expect(mockNetwork.connect).not.toHaveBeenCalled();
      expect(plugin.isRunning).toBe(false);
      expect(onReady).not.toHaveBeenCalled();

      firstCdj.resolve();
      await Promise.resolve();
      expect(plugin.isRunning).toBe(false);
      expect(mockNetwork.connect).not.toHaveBeenCalled();
    });

    it("stop waits for a pending bringOnline to settle and closes its network", async () => {
      const { bringOnline } = await import("alphatheta-connect");
      const online = deferred<typeof mockNetwork>();
      vi.mocked(bringOnline).mockImplementationOnce(() => online.promise as never);

      const starting = plugin.start();
      let stopped = false;
      const stopping = plugin.stop().then(() => {
        stopped = true;
      });

      await new Promise((resolve) => setTimeout(resolve, 10));
      expect(stopped).toBe(false);

      online.resolve(mockNetwork);
      await stopping;
      expect(mockNetwork.close).toHaveBeenCalledTimes(1);
      await expect(starting).resolves.toBeUndefined();

      expect(mockNetwork.autoconfigFromPeers).not.toHaveBeenCalled();
      expect(mockNetwork.connect).not.toHaveBeenCalled();
      expect(plugin.isRunning).toBe(false);
    });

    it("stop closes the network's sockets", async () => {
      // The real disconnect() returns close() detached from its instance, which throws
      mockNetwork.disconnect.mockImplementationOnce(() => (() => {
        throw new TypeError("Cannot read private member from an object whose class did not declare it");
      }) as never);

      await plugin.start();
      await plugin.stop();

      expect(mockNetwork.disconnect).toHaveBeenCalledTimes(1);
      expect(mockNetwork.close).toHaveBeenCalledTimes(1);
    });

    it("has settled the cancelled start by the time stop returns, so a new start is clean", async () => {
      const staleCdj = deferred();
      mockNetwork.autoconfigFromPeers.mockImplementationOnce(() => staleCdj.promise);

      let staleSettled = false;
      const stale = plugin.start().then(() => {
        staleSettled = true;
      });
      await vi.waitFor(() => expect(mockNetwork.autoconfigFromPeers).toHaveBeenCalled());
      await plugin.stop();
      expect(staleSettled).toBe(true);
      await stale;

      const onReady = vi.fn();
      plugin.on("ready", onReady);
      await plugin.start();
      expect(plugin.isRunning).toBe(true);
      expect(onReady).toHaveBeenCalledTimes(1);
      expect(mockNetwork.connect).toHaveBeenCalledTimes(1);
      mockNetwork.close.mockClear();
      mockNetwork.disconnect.mockClear();

      staleCdj.resolve();
      await Promise.resolve();

      expect(plugin.isRunning).toBe(true);
      expect(mockNetwork.connect).toHaveBeenCalledTimes(1);
      expect(mockNetwork.close).not.toHaveBeenCalled();
      expect(mockNetwork.disconnect).not.toHaveBeenCalled();
    });

    it("rejects a second start while the first is still pending", async () => {
      const firstCdj = deferred();
      mockNetwork.autoconfigFromPeers.mockImplementationOnce(() => firstCdj.promise);

      const starting = plugin.start();
      await expect(plugin.start()).rejects.toThrow("already running");

      firstCdj.resolve();
      await starting;
    });

    it("closes the sockets when start fails before the network is configured", async () => {
      mockNetwork.autoconfigFromPeers.mockRejectedValueOnce(
        new Error("Unable to determine network interface")
      );

      await expect(plugin.start()).rejects.toThrow("Unable to determine network interface");

      expect(mockNetwork.close).toHaveBeenCalledTimes(1);
      expect(plugin.isRunning).toBe(false);
    });
  });
});
