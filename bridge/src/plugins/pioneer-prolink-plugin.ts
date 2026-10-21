/**
 * Pioneer PRO DJ LINK Equipment Source Plugin
 *
 * Connects to Pioneer DJ equipment (CDJs) via the PRO DJ LINK protocol.
 * Uses the prolink-connect library to join the network as a virtual device,
 * monitor CDJ status packets, and query track metadata from CDJ databases.
 *
 * Important caveats:
 *   - Cannot coexist with Rekordbox on the same machine (same protocol slots)
 *   - Requires Ethernet connection — CDJs must be on the same LAN
 *   - On-air detection requires a DJM mixer connected via Ethernet;
 *     without one, isOnAir defaults to true (fader becomes a no-op)
 *   - Occupies one virtual CDJ slot (max 5 real CDJs when plugin is running)
 */
import type { PluginMeta } from "./plugin-registry.js";
import { bringOnline, CDJStatus, DeviceType } from "alphatheta-connect";
import type { Device, ProlinkNetwork } from "alphatheta-connect";
import { TypedEventEmitter } from "../shared/typed-event-emitter.js";

import type {
  EquipmentSourcePlugin,
  PluginCapabilities,
  PluginConfigOption,
  PluginInfo,
  PluginEventMap,
  PluginEventArguments,
} from "./plugin-types.js";

export class PioneerProlinkPlugin extends TypedEventEmitter<PluginEventArguments> implements EquipmentSourcePlugin {
  static readonly metadata: PluginMeta = {
    info: {
      id: "pioneer-prolink",
      name: "Pioneer PRO DJ LINK",
      description: "Connects to Pioneer DJ equipment via PRO DJ LINK network",
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

  readonly info: PluginInfo = structuredClone(PioneerProlinkPlugin.metadata.info);

  readonly capabilities: PluginCapabilities = structuredClone(PioneerProlinkPlugin.metadata.capabilities);

  readonly configOptions: readonly PluginConfigOption[] = structuredClone(PioneerProlinkPlugin.metadata.configOptions);

  private running = false;
  private network: ProlinkNetwork | null = null;

  /** Per-deck track ID cache for detecting track changes */
  private deckTrackIds = new Map<string, number>();

  /** Per-deck AbortController for cancelling stale metadata fetches */
  private deckFetchControllers = new Map<string, AbortController>();

  /** Per-deck retry timers for metadata retry delay */
  private deckRetryTimers = new Map<string, ReturnType<typeof setTimeout>>();

  get isRunning(): boolean {
    return this.running;
  }

  async start(_config?: Record<string, unknown>): Promise<void> {
    if (this.running) {
      throw new Error("Pioneer PRO DJ LINK plugin is already running");
    }

    // A previous shutdown may have left the device network active. Retry that cleanup
    // before acquiring another virtual device slot.
    if (this.network) {
      await this.disconnectNetwork(this.network);
    }

    this.deckTrackIds.clear();
    this.abortAllFetches();

    this.emit("log", "Bringing PRO DJ LINK network online...");
    const network = await bringOnline();
    this.network = network;

    try {
      this.emit("log", "Waiting for first CDJ to appear...");
      await network.autoconfigFromPeers();

      this.emit("log", "Connecting as virtual device...");
      network.connect();
    } catch (err) {
      await this.disconnectNetwork(network);
      throw err;
    }

    this.running = true;

    this.wireProlinkEvents();
    this.emit("ready");
    this.emit("log", "Connected to PRO DJ LINK network");
  }

  async stop(): Promise<void> {
    if (!this.running && !this.network) return;

    this.running = false;
    this.deckTrackIds.clear();
    this.abortAllFetches();

    try {
      if (this.network) await this.disconnectNetwork(this.network);
    } finally {
      this.removeAllListeners();
    }
  }

  private async disconnectNetwork(network: ProlinkNetwork): Promise<void> {
    try {
      await network.disconnect()();
      if (this.network === network) this.network = null;
    } catch (cause) {
      throw new Error("Failed to disconnect from PRO DJ LINK network; cleanup can be retried", {
        cause,
      });
    }
  }

  private wireProlinkEvents(): void {
    if (!this.network) return;

    // Device discovery
    this.network.deviceManager.on("connected", (device: Device) => {
      if (!this.running || device.type !== DeviceType.CDJ) return;
      this.emit("log", `CDJ connected: ${device.name} (ID ${device.id})`);
      this.emit("connection", { connected: true, deviceName: device.name });
    });

    this.network.deviceManager.on("disconnected", (device: Device) => {
      if (!this.running || device.type !== DeviceType.CDJ) return;
      this.emit("log", `CDJ disconnected: ${device.name} (ID ${device.id})`);
      this.emit("connection", { connected: false, deviceName: device.name });
    });

    // CDJ status updates — statusEmitter is guaranteed non-null after connect()
    const statusEmitter = this.network.statusEmitter;
    if (!statusEmitter) return;

    statusEmitter.on("status", (status: CDJStatus.State) => {
      if (!this.running) return;
      const deckId = String(status.deviceId);

      // Play state
      const isPlaying = status.playState === CDJStatus.PlayState.Playing;
      this.emit("playState", { deckId, isPlaying });

      // Fader (on-air maps to binary fader level)
      const level = status.isOnAir ? 1.0 : 0.0;
      this.emit("fader", { deckId, level });

      // Master deck
      if (status.isMaster) {
        this.emit("masterDeck", { deckId });
      }

      // Track change detection
      this.handleTrackChange(status, deckId);
    });
  }

  private handleTrackChange(status: CDJStatus.State, deckId: string): void {
    const previousTrackId = this.deckTrackIds.get(deckId);
    const currentTrackId = status.trackId;

    if (currentTrackId === previousTrackId) return;

    this.deckTrackIds.set(deckId, currentTrackId);

    // Track unloaded
    if (currentTrackId === 0) {
      this.emit("track", { deckId, track: null });
      return;
    }

    // Fetch metadata asynchronously
    this.fetchTrackMetadata(status, deckId);
  }

  private static readonly METADATA_TIMEOUT_MS = 10_000;
  private static readonly METADATA_RETRY_DELAY_MS = 3_000;

  private fetchTrackMetadata(status: CDJStatus.State, deckId: string): void {
    // Abort any in-flight metadata fetch for this deck (prevents stale results)
    this.abortDeckFetch(deckId);

    const controller = new AbortController();
    this.deckFetchControllers.set(deckId, controller);

    this.attemptMetadataFetch(status, deckId, controller.signal, true);
  }

  private attemptMetadataFetch(
    status: CDJStatus.State,
    deckId: string,
    signal: AbortSignal,
    allowRetry: boolean,
  ): void {
    const db = this.network?.db;
    if (!db) return;

    const metadataPromise = db.getMetadata({
      deviceId: status.trackDeviceId,
      trackSlot: status.trackSlot,
      trackType: status.trackType,
      trackId: status.trackId,
    });

    let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
    const timeoutPromise = new Promise<never>((_resolve, reject) => {
      timeoutHandle = setTimeout(
        () => reject(new Error("Metadata fetch timed out")),
        PioneerProlinkPlugin.METADATA_TIMEOUT_MS,
      );
    });

    Promise.race([metadataPromise, timeoutPromise])
      .then((track) => {
        clearTimeout(timeoutHandle);
        if (signal.aborted) return;

        if (!track) {
          this.emit("log", `No metadata for track ${status.trackId} on deck ${deckId}`);
          // Emit partial track so state machine still transitions
          this.emit("track", {
            deckId,
            track: { title: "Unknown Track", artist: "Unknown" },
          });
          return;
        }

        this.emit("track", {
          deckId,
          track: {
            title: track.title,
            artist: track.artist?.name ?? "",
            album: track.album?.name,
          },
        });

        this.emit(
          "log",
          `Track on deck ${deckId}: "${track.title}" by ${track.artist?.name ?? "Unknown"}`,
        );
      })
      .catch((err: unknown) => {
        clearTimeout(timeoutHandle);
        if (signal.aborted) return;

        const message = err instanceof Error ? err.message : String(err);
        this.emit("log", `Failed to fetch metadata for track ${status.trackId}: ${message}`);

        if (allowRetry) {
          // Retry once after a short delay (tracked so it can be cancelled on stop/abort)
          this.emit("log", `Retrying metadata fetch for track ${status.trackId} on deck ${deckId}...`);
          const retryTimer = setTimeout(() => {
            this.deckRetryTimers.delete(deckId);
            if (signal.aborted || !this.running) return;
            // Verify the track hasn't changed during the delay
            if (this.deckTrackIds.get(deckId) !== status.trackId) return;
            this.attemptMetadataFetch(status, deckId, signal, false);
          }, PioneerProlinkPlugin.METADATA_RETRY_DELAY_MS);
          this.deckRetryTimers.set(deckId, retryTimer);
        } else {
          // Retry exhausted — emit partial track so DeckStateManager still transitions
          this.emit("log", `Metadata unavailable for track ${status.trackId} on deck ${deckId}, emitting partial data`);
          this.emit("track", {
            deckId,
            track: { title: "Unknown Track", artist: "Unknown" },
          });
        }
      });
  }

  private abortDeckFetch(deckId: string): void {
    const existing = this.deckFetchControllers.get(deckId);
    if (existing) {
      existing.abort();
      this.deckFetchControllers.delete(deckId);
    }
    const existingTimer = this.deckRetryTimers.get(deckId);
    if (existingTimer) {
      clearTimeout(existingTimer);
      this.deckRetryTimers.delete(deckId);
    }
  }

  private abortAllFetches(): void {
    for (const controller of this.deckFetchControllers.values()) {
      controller.abort();
    }
    this.deckFetchControllers.clear();
    for (const timer of this.deckRetryTimers.values()) {
      clearTimeout(timer);
    }
    this.deckRetryTimers.clear();
  }
}
