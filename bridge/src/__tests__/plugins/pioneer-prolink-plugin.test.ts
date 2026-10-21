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
} from "../../plugins/plugin-types.js";

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
const { PioneerProlinkPlugin } = await import("../../plugins/pioneer-prolink-plugin.js");

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

      // Regression for baseline 57cfcdc6867f: deduplication must be driven by track ID,
      // not by waiting long enough for a duplicate asynchronous metadata result.
      expect(mockDb.getMetadata).toHaveBeenCalledOnce();
      await vi.waitFor(() => expect(tracks).toHaveLength(1));
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
});
