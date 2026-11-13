/**
 * StageLinQ Equipment Source Plugin
 *
 * Extracts the StageLinQ event wiring from index.ts into a plugin that
 * implements the EquipmentSourcePlugin interface. Connects to Denon DJ
 * equipment via the stagelinq npm package and emits normalized events.
 */
import { EventEmitter } from "events";
import { StageLinq } from "stagelinq";

import type {
  EquipmentSourcePlugin,
  PluginCapabilities,
  PluginConfigOption,
  PluginInfo,
} from "../plugin-types.js";

export class StageLinqPlugin extends EventEmitter implements EquipmentSourcePlugin {
  readonly info: PluginInfo = {
    id: "stagelinq",
    name: "Denon StageLinQ",
    description: "Connects to Denon DJ equipment via StageLinQ protocol",
  };

  readonly capabilities: PluginCapabilities = {
    multiDeck: true,
    playState: true,
    faderLevel: true,
    masterDeck: true,
    albumMetadata: true,
  };

  readonly configOptions: readonly PluginConfigOption[] = [];

  private static readonly CONNECT_TIMEOUT_MS = 30_000;

  private running = false;
  private disconnectFailed = false;
  private stopLogging: (() => void) | null = null;
  // Identifies the current start attempt; stop() and a newer start() bump it.
  private runToken = 0;
  // Settles (never rejects) when the library call a start() is awaiting is done.
  private inFlight: Promise<void> | null = null;
  // Settles when a stop() has finished tearing the library down.
  private stopping: Promise<void> | null = null;

  get isRunning(): boolean {
    return this.running;
  }

  async start(): Promise<void> {
    if (this.running) {
      throw new Error("StageLinQ plugin is already running");
    }

    this.running = true;
    const token = ++this.runToken;
    const isStale = () => token !== this.runToken;

    // A previous stop() still owns the library; the options setter would
    // orphan a connect it has not finished waiting for.
    await this.stopping;
    if (isStale()) return;

    // A failed shutdown leaves upstream connected and ignores a new logger.
    // Recover that connection before configuring a fresh run.
    if (this.disconnectFailed) {
      try {
        await this.track(StageLinq.disconnect());
        this.disconnectFailed = false;
      } catch (error) {
        // A stop() that overtook us retries the disconnect and owns the flag.
        if (isStale()) return;
        this.running = false;
        throw error;
      }
      if (isStale()) return;
    }

    this.configureLibrary();

    // Wire event handlers AFTER options are set
    this.wireEvents();

    this.emit("log", "Connecting to StageLinQ network...");

    try {
      await this.connectWithTimeout();
    } catch (error) {
      // A stopped start is not a failure; stop() owns the cleanup.
      if (isStale()) return;
      throw error;
    }
    // stop() waited for the connect to settle and then disconnected.
    if (isStale()) return;
    this.emit("log", "Listening for DJ equipment...");
  }

  async stop(): Promise<void> {
    if (!this.running) return;

    this.running = false;
    const token = ++this.runToken;

    const done = this.shutdown(token);
    this.stopping = done;
    await done;
  }

  private async shutdown(token: number): Promise<void> {
    // disconnect() is a no-op until connect() resolves, so wait for the
    // in-flight library call (bounded by the library's own announce timeout,
    // not the plugin's 30s timer) before tearing down.
    await this.inFlight;

    try {
      await StageLinq.disconnect();
      this.disconnectFailed = false;
    } catch {
      // Keep stop best-effort, but require recovery before the next start.
      this.disconnectFailed = true;
    }

    this.stopLogging?.();
    this.stopLogging = null;
    // A start() queued behind this stop owns the listeners attached for it.
    if (token === this.runToken) this.removeAllListeners();
  }

  private configureLibrary(): void {
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
  }

  private async connectWithTimeout(): Promise<void> {
    const connectPromise = this.track(StageLinq.connect());
    let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
    const timeoutPromise = new Promise<never>((_resolve, reject) => {
      timeoutHandle = setTimeout(
        () => reject(new Error("No Denon equipment found on network within 30s")),
        StageLinqPlugin.CONNECT_TIMEOUT_MS,
      );
    });

    try {
      await Promise.race([connectPromise, timeoutPromise]);
    } finally {
      clearTimeout(timeoutHandle);
    }
  }

  // Remember the pending library call so stop() can wait for it to settle.
  private track<T>(op: Promise<T>): Promise<T> {
    const settled = op.then(
      () => undefined,
      () => undefined,
    );
    this.inFlight = settled;
    void settled.then(() => {
      if (this.inFlight === settled) this.inFlight = null;
    });
    return op;
  }

  private wireEvents(): void {
    // Handle now-playing events (track metadata + play state)
    StageLinq.devices.on("nowPlaying", (status) => {
      const deckId = status.deck || "1";
      const title = status.title || "";
      const artist = status.artist || "";

      if (!title) {
        this.emit("track", { deckId, track: null });
        return;
      }

      this.emit("track", {
        deckId,
        track: {
          title,
          artist,
          album: (status as unknown as Record<string, unknown>).album as string | undefined,
        },
      });

      // Forward explicit play state
      if (typeof status.play === "boolean" || typeof status.playState === "boolean") {
        const isPlaying = status.play === true || status.playState === true;
        this.emit("playState", { deckId, isPlaying });
      }
    });

    // Handle state changes (play state, faders, master deck)
    StageLinq.devices.on("stateChanged", (status) => {
      if (!status.deck) return;

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
    StageLinq.devices.on("connected", (info) => {
      const deviceName = info?.software?.name || "Unknown Device";
      const deviceVersion = info?.software?.version || "unknown";
      const deviceAddress = info?.address || "unknown";
      this.emit("log", `Device connected: ${deviceName} v${deviceVersion} at ${deviceAddress}`);
      this.emit("connection", { connected: true, deviceName });
    });

    // Handle all devices ready
    StageLinq.devices.on("ready", () => {
      this.emit("log", "All devices ready — StateMap initialized");
      this.emit("ready");
    });

    // Handle device disconnect
    (StageLinq.devices as NodeJS.EventEmitter).on("disconnect", () => {
      this.emit("log", "Device disconnected");
      this.emit("connection", { connected: false });
    });
  }
}
