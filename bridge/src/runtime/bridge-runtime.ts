import { BridgeClient } from "../transport/bridge.js";
import type { CircuitState } from "../transport/circuit-breaker.js";
import { CommandPoller, type BridgeCommand } from "../transport/command-poller.js";
import { toDeckStateManagerConfig, type BridgeConfig } from "./config.js";
import type { DeckLiveEvent, DeckStateSnapshot } from "../deck/deck-state.js";
import { Logger } from "../shared/logger.js";
import { PluginBridge } from "../plugins/plugin-bridge.js";
import type { EquipmentSourcePlugin, PluginConnectionEvent } from "../plugins/plugin-types.js";
import { EventArgumentMap, TypedEventEmitter } from "../shared/typed-event-emitter.js";
import { MILLISECONDS_PER_SECOND } from "../shared/time-units.js";
import type { LogLevel } from "../shared/logger.js";

export interface BridgeRuntimeSnapshot {
  readonly running: boolean;
  readonly connectedDevice: string | null;
  readonly pluginId: string;
  readonly deckCount: number;
  readonly circuitBreakerState: CircuitState;
  readonly bufferSize: number;
  readonly uptimeSeconds: number;
  readonly backendReachable: boolean;
  readonly deckStates: readonly DeckStateSnapshot[];
}

/** Events exposed to adapters of the shared bridge session runtime. */
export interface BridgeRuntimeEventMap {
  statusChanged: BridgeRuntimeSnapshot;
  authenticationError: void;
  equipmentError: Error;
  deckLive: DeckLiveEvent;
  connection: PluginConnectionEvent;
  clearNowPlaying: void;
  ping: void;
  log: { readonly message: string; readonly level: LogLevel };
  ready: void;
}

/** Owns the equipment, command queue and backend client for one CLI session. */
type BridgeRuntimeEventArguments = EventArgumentMap<BridgeRuntimeEventMap>;

export class BridgeRuntime extends TypedEventEmitter<BridgeRuntimeEventArguments> {
  private readonly config: BridgeConfig;
  private readonly client: BridgeClient;
  private readonly bridge: PluginBridge;
  private readonly poller: CommandPoller;
  private readonly log = new Logger("Bridge");
  private readonly pendingPosts = new Set<Promise<void>>();
  private commandQueue = Promise.resolve();
  private stopping: Promise<void> | null = null;
  private running = false;
  private connectedDevice: string | null = null;
  private startedAt: number | null = null;
  private backendReachable = true;
  private pendingAuthenticationErrors = 0;

  constructor(
    config: BridgeConfig,
    plugin: EquipmentSourcePlugin,
    options: { readonly stopOnUnauthorized?: boolean } = {},
  ) {
    super();
    this.config = { ...config };
    const handleAuthenticationError = options.stopOnUnauthorized ? () => {
      this.pendingAuthenticationErrors += 1;
      this.emit("authenticationError");
    } : undefined;
    this.client = new BridgeClient(
      {
        apiUrl: config.apiUrl,
        apiKey: config.apiKey,
        eventCode: config.eventCode,
        minPlaySeconds: config.minPlaySeconds,
      },
      handleAuthenticationError,
    );
    this.bridge = new PluginBridge(plugin, toDeckStateManagerConfig(config));
    this.poller = new CommandPoller(this.client.getCircuitBreaker(), this.log.child("CommandPoller"));
    this.poller.on("authenticationError", () => handleAuthenticationError?.());
    this.wireEvents();
  }

  async start(pluginConfig?: Record<string, unknown>): Promise<void> {
    if (this.stopping) throw new Error("Bridge runtime has stopped");
    if (this.running) throw new Error("Bridge runtime is already running");
    this.running = true;
    this.startedAt = Date.now();
    this.emitStatus();
    try {
      await this.bridge.start(pluginConfig);
      if (!this.running || this.stopping) {
        await this.stop();
        return;
      }
      this.poller.start(this.config.apiUrl, this.config.apiKey, this.config.eventCode);
      const initialStatusPost = this.client.postBridgeStatus(true, undefined, this.enrichedStatus());
      this.trackPendingPost(initialStatusPost);
      const online = await initialStatusPost;
      this.backendReachable = this.pendingAuthenticationErrors > 0 ? true : online;
      if (this.pendingAuthenticationErrors > 0) this.pendingAuthenticationErrors -= 1;
      this.emitStatus();
    } catch (error) {
      try {
        await this.stop();
      } catch (shutdownError) {
        this.log.error(`Cleanup after startup failure also failed: ${shutdownError instanceof Error ? shutdownError.message : String(shutdownError)}`);
      }
      throw error;
    }
  }

  /** Stop intake immediately, then finish active work before the final offline status. */
  stop(): Promise<void> {
    if (!this.stopping) {
      this.running = false;
      this.poller.stop();
      this.emitStatus();
      this.stopping = this.shutdown();
    }
    return this.stopping;
  }

  private async shutdown(): Promise<void> {
    let cleanupError: unknown;
    let hasCleanupError = false;
    const attempt = async (operation: () => Promise<unknown>): Promise<void> => {
      try {
        await operation();
      } catch (error) {
        if (!hasCleanupError) {
          hasCleanupError = true;
          cleanupError = error;
        }
      }
    };

    await attempt(() => this.commandQueue);
    this.bridge.removeAllListeners();
    await attempt(() => this.bridge.stop());
    await attempt(() => Promise.all(this.pendingPosts));
    await attempt(() => this.client.clearNowPlaying());
    await attempt(() => this.client.postBridgeStatus(false));
    this.connectedDevice = null;
    this.emitStatus();
    if (hasCleanupError) throw cleanupError;
  }

  /** Read-only session state for adapters such as the Electron UI. */
  getSnapshot(): BridgeRuntimeSnapshot {
    const backend = this.client.getDetailedStatus();
    const decks = this.bridge.getDeckStatusSnapshot();
    return {
      running: this.running,
      connectedDevice: this.connectedDevice,
      pluginId: this.bridge.pluginId,
      deckCount: decks.deckCount,
      circuitBreakerState: this.client.getCircuitBreaker().getState(),
      bufferSize: backend.buffer_size,
      uptimeSeconds: this.startedAt === null ? 0 : Math.floor((Date.now() - this.startedAt) / MILLISECONDS_PER_SECOND),
      backendReachable: this.backendReachable,
      deckStates: decks.deckStates,
    };
  }

  /** App adapters may expose these controls without owning equipment lifecycle. */
  resetDecks(): void {
    if (!this.running) throw new Error("Bridge runtime is not running");
    this.bridge.resetDecks();
    this.emitStatus();
  }

  reconnect(): Promise<void> {
    if (!this.running) return Promise.reject(new Error("Bridge runtime is not running"));
    return this.bridge.reconnect();
  }

  restart(): Promise<void> {
    if (!this.running) return Promise.reject(new Error("Bridge runtime is not running"));
    return this.bridge.restart();
  }

  private emitStatus(): void {
    this.emit("statusChanged", this.getSnapshot());
  }

  private enrichedStatus() {
    return {
      ...this.client.getDetailedStatus(),
      plugin_id: this.bridge.pluginId,
      deck_count: this.bridge.getDeckStatusSnapshot().deckCount,
    };
  }

  private wireEvents(): void {
    this.bridge.on("log", (message: string) => {
      this.logMessage(message);
      this.emitStatus();
    });
    this.bridge.on("error", (error: Error) => {
      this.logMessage(`Equipment error: ${error.message}`, "error");
      this.emit("equipmentError", error);
    });
    this.bridge.on("deckLive", (event: DeckLiveEvent) => {
      const { deckId, track } = event;
      if (!this.running || this.stopping || this.client.shouldSkipTrack(track.artist, track.title)) return;
      this.client.updateLastTrack(track.artist, track.title);
      this.emit("deckLive", event);
      this.report(this.client.postNowPlaying(track.title, track.artist, track.album, deckId, this.bridge.pluginId));
      this.emitStatus();
    });
    this.bridge.on("heartbeat", () => {
      if (this.running && !this.stopping) this.report(this.client.postBridgeStatus(true, this.connectedDevice ?? undefined, this.enrichedStatus()));
    });
    this.bridge.on("clearNowPlaying", () => {
      if (this.running && !this.stopping) {
        this.emit("clearNowPlaying");
        this.report(this.client.clearNowPlaying());
      }
    });
    this.bridge.on("connection", (event: PluginConnectionEvent) => {
      if (!this.running || this.stopping) return;
      this.connectedDevice = event.connected ? event.deviceName ?? "Unknown Device" : null;
      this.emit("connection", event);
      this.emitStatus();
      this.report(this.client.postBridgeStatus(
        event.connected, event.deviceName, event.connected ? this.enrichedStatus() : undefined,
      ));
    });
    this.bridge.on("ready", () => this.emit("ready"));
    this.client.getCircuitBreaker().on("stateChange", () => this.emitStatus());
    this.poller.on("command", (type: string, command: BridgeCommand) => {
      if (this.stopping) return;
      if (type === "ping") this.emit("ping");
      this.commandQueue = this.commandQueue.then(async () => {
        if (!this.stopping) await this.executeCommand(type, command);
      });
    });
  }

  private report(post: Promise<boolean>): void {
    const pending = post.then((success) => {
      if (this.pendingAuthenticationErrors > 0) {
        this.pendingAuthenticationErrors -= 1;
        this.backendReachable = true;
      } else {
        this.backendReachable = success;
      }
      this.emitStatus();
    }, (error: unknown) => {
      this.backendReachable = false;
      this.log.error(`Backend update failed: ${error instanceof Error ? error.message : String(error)}`);
      this.emitStatus();
    }).finally(() => this.pendingPosts.delete(pending));
    this.pendingPosts.add(pending);
  }

  private trackPendingPost(post: Promise<unknown>): void {
    let pending: Promise<void>;
    pending = post
      .then(() => undefined, () => undefined)
      .finally(() => this.pendingPosts.delete(pending));
    this.pendingPosts.add(pending);
  }

  private async executeCommand(type: string, command?: BridgeCommand): Promise<void> {
    this.log.info(`Executing command: ${type}`);
    try {
      switch (type) {
        case "ping": this.log.info("Ping received from dashboard"); break;
        case "reset_decks": this.resetDecks(); break;
        case "reconnect": await this.reconnect(); break;
        case "restart": await this.restart(); break;
        case "setbuilder_transport": this.logSetbuilderTransportCommand(command?.payload ?? {}); break;
        default: this.logMessage(`Unknown command type: ${type}`, "warn");
      }
    } catch (error) {
      this.logMessage(`Command "${type}" failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  }

  private logSetbuilderTransportCommand(payload: Record<string, unknown>): void {
    const action = typeof payload.action === "string" ? payload.action : "unknown";
    const title = typeof payload.title === "string" ? payload.title : "";
    const position = typeof payload.position_sec === "number" ? payload.position_sec : 0;
    this.logMessage(`Setbuilder transport command received: ${action}${title ? ` "${title}"` : ""} @ ${position.toFixed(1)}s`);
  }

  private logMessage(message: string, level: "info" | "warn" | "error" = "info"): void {
    this.log[level](message);
    this.emit("log", { message, level });
  }
}
