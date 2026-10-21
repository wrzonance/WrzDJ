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

    it("retains failed disconnect for cleanup before a new connection", async () => {
      const { bringOnline } = await import("alphatheta-connect");
      const bringOnlineSpy = vi.mocked(bringOnline);
      mockNetwork.disconnect
        .mockReturnValueOnce(() => Promise.reject(new Error("socket error")))
        .mockReturnValue(() => Promise.resolve(undefined));
      await plugin.start();

      await expect(plugin.stop()).rejects.toThrow("Failed to disconnect from PRO DJ LINK network");
      expect(plugin.isRunning).toBe(false);
      expect(bringOnlineSpy).toHaveBeenCalledTimes(1);

      await plugin.start();

      // Regression for baseline 57cfcdc6867f: failed shutdown cleanup was discarded,
      // allowing a new network connection to start while the old one remained open.
      expect(mockNetwork.disconnect).toHaveBeenCalledTimes(2);
      expect(bringOnlineSpy).toHaveBeenCalledTimes(2);
      await plugin.stop();
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
});
