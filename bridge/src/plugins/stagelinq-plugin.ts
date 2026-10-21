/**
 * StageLinQ Equipment Source Plugin
 *
 * Extracts the StageLinQ event wiring from index.ts into a plugin that
 * implements the EquipmentSourcePlugin interface. Connects to Denon DJ
 * equipment via the stagelinq npm package and emits normalized events.
 */
import type { PluginMeta } from "./plugin-registry.js";
import { EventEmitter } from "events";
import { StageLinq } from "stagelinq";
import { TypedEventEmitter } from "../shared/typed-event-emitter.js";

type StageLinqDeviceListener = (...args: unknown[]) => void;

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

import type {
  EquipmentSourcePlugin,
  PluginCapabilities,
  PluginConfigOption,
  PluginInfo,
  PluginEventMap,
  PluginEventArguments,
} from "./plugin-types.js";

export class StageLinqPlugin extends TypedEventEmitter<PluginEventArguments> implements EquipmentSourcePlugin {
  static readonly metadata: PluginMeta = {
    info: {
      id: "stagelinq",
      name: "Denon StageLinQ",
      description: "Connects to Denon DJ equipment via StageLinQ protocol",
    },
    capabilities: {
      multiDeck: true,
      playState: true,
      faderLevel: true,
      masterDeck: true,
      albumMetadata: true,
    },
    configOptions: []
  };

  readonly info: PluginInfo = structuredClone(StageLinqPlugin.metadata.info);

  readonly capabilities: PluginCapabilities = structuredClone(StageLinqPlugin.metadata.capabilities);

  readonly configOptions: readonly PluginConfigOption[] = structuredClone(StageLinqPlugin.metadata.configOptions);

  private static readonly CONNECT_TIMEOUT_MS = 30_000;

  private running = false;
  private disconnectFailed = false;
  private stopLogging: (() => void) | null = null;
  private deviceEmitter: EventEmitter | null = null;
  private readonly deviceListeners: Array<{ event: string; listener: StageLinqDeviceListener }> = [];

  get isRunning(): boolean {
    return this.running;
  }

  async start(): Promise<void> {
    if (this.running) {
      throw new Error("StageLinQ plugin is already running");
    }

    this.running = true;

    // A failed shutdown leaves upstream connected and ignores a new logger.
    // Recover that connection before configuring a fresh run.
    if (this.disconnectFailed) {
      try {
        await StageLinq.disconnect();
        this.disconnectFailed = false;
      } catch (error) {
        this.running = false;
        throw error;
      }
    }

    // Each run owns its forwarding callback. Releasing it also silences late
    // messages from an old library instance after this plugin starts again.
    let listener: ((...args: unknown[]) => void) | null = (...args) => {
      this.emit("log", args.map(String).join(" "));
    };
    this.stopLogging = () => {
      listener = null;
    };
    const forward = (level: string, ...args: unknown[]) => listener?.(level, ...args);

    // Configure StageLinQ options BEFORE accessing StageLinq.devices or
    // StageLinq.logger. The options setter resets the internal singleton.
    StageLinq.options = {
      downloadDbSources: false,
      enableFileTranfer: true,
      logger: {
        trace: (...args) => forward("trace", ...args),
        debug: (...args) => forward("debug", ...args),
        info: (...args) => forward("info", ...args),
        warn: (...args) => forward("warn", ...args),
        error: (...args) => forward("error", ...args),
      },
    };

    // Wire event handlers AFTER options are set
    this.wireStageLinqEvents();

    this.emit("log", "Connecting to StageLinQ network...");

    const connectPromise = StageLinq.connect();
    let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
    const timeoutPromise = new Promise<never>((_resolve, reject) => {
      timeoutHandle = setTimeout(
        () => reject(new Error("No Denon equipment found on network within 30s")),
        StageLinqPlugin.CONNECT_TIMEOUT_MS,
      );
    });

    try {
      await Promise.race([connectPromise, timeoutPromise]);
    } catch (error) {
      this.running = false;
      this.stopLogging?.();
      this.stopLogging = null;
      this.removeDeviceListeners();
      try {
        await StageLinq.disconnect();
      } catch {
        this.disconnectFailed = true;
      }
      throw error;
    } finally {
      clearTimeout(timeoutHandle);
    }
    this.emit("log", "Listening for DJ equipment...");
  }

  async stop(): Promise<void> {
    if (!this.running) return;

    this.running = false;
    this.removeDeviceListeners();

    try {
      await StageLinq.disconnect();
    } catch {
      // Keep stop best-effort, but require recovery before the next start.
      this.disconnectFailed = true;
    }

    this.stopLogging?.();
    this.stopLogging = null;
  }

  private wireStageLinqEvents(): void {
    const devices = StageLinq.devices;
    const emitter = devices as EventEmitter;
    this.deviceEmitter = emitter;
    const listen = (event: string, listener: StageLinqDeviceListener): void => {
      emitter.on(event, listener);
      this.deviceListeners.push({ event, listener });
    };

    // Handle now-playing events (track metadata + play state)
    listen("nowPlaying", (payload) => {
      const status = asRecord(payload);
      if (!status) return;
      const deckId = typeof status.deck === "string" && status.deck ? status.deck : "1";
      const title = typeof status.title === "string" ? status.title : "";
      const artist = typeof status.artist === "string" ? status.artist : "";

      if (!title) {
        this.emit("track", { deckId, track: null });
        return;
      }

      this.emit("track", {
        deckId,
        track: {
          title,
          artist,
          album: typeof status.album === "string" ? status.album : undefined,
        },
      });

      // Forward explicit play state
      if (typeof status.play === "boolean" || typeof status.playState === "boolean") {
        const isPlaying = status.play === true || status.playState === true;
        this.emit("playState", { deckId, isPlaying });
      }
    });

    // Handle state changes (play state, faders, master deck)
    listen("stateChanged", (payload) => {
      const status = asRecord(payload);
      if (!status || typeof status.deck !== "string" || !status.deck) return;

      const deckId = status.deck;

      if (typeof status.play === "boolean" || typeof status.playState === "boolean") {
        const isPlaying = status.play === true || status.playState === true;
        this.emit("playState", { deckId, isPlaying });
      }

      if (typeof status.externalMixerVolume === "number") {
        this.emit("fader", { deckId, level: status.externalMixerVolume });
      }

      if (status.masterStatus === true) {
        this.emit("masterDeck", { deckId });
      }
    });

    // Handle per-device connection
    listen("connected", (payload) => {
      const info = asRecord(payload);
      const software = asRecord(info?.software);
      const deviceName = typeof software?.name === "string" && software.name ? software.name : "Unknown Device";
      const deviceVersion = typeof software?.version === "string" && software.version ? software.version : "unknown";
      const deviceAddress = typeof info?.address === "string" && info.address ? info.address : "unknown";
      this.emit("log", `Device connected: ${deviceName} v${deviceVersion} at ${deviceAddress}`);
      this.emit("connection", { connected: true, deviceName });
    });

    // Handle all devices ready
    listen("ready", () => {
      this.emit("log", "All devices ready — StateMap initialized");
      this.emit("ready");
    });

    // Handle device disconnect
    listen("disconnect", () => {
      this.emit("log", "Device disconnected");
      this.emit("connection", { connected: false });
    });
  }

  private removeDeviceListeners(): void {
    const devices = this.deviceEmitter;
    if (!devices) return;
    for (const { event, listener } of this.deviceListeners) {
      devices.removeListener(event, listener);
    }
    this.deviceListeners.length = 0;
    this.deviceEmitter = null;
  }
}
