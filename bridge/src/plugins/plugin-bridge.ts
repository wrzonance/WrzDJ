/**
 * PluginBridge — translation layer between equipment source plugins and DeckStateManager.
 *
 * Normalizes plugin events into DeckStateManager calls.
 * Synthesizes missing data based on plugin capabilities:
 *   - playState=false → calls updatePlayState(true) when metadata changes
 *   - multiDeck=false → assigns virtual deck ID "1"
 */
import { DeckStateManager } from "../deck/deck-state-manager.js";
import type {
  DeckLiveEvent,
  DeckStateManagerConfig,
  DeckStateSnapshot,
  DeckStatusSnapshot,
} from "../deck/deck-state.js";
import type { TrackInfo } from "../shared/track-types.js";
import type {
  EquipmentSourcePlugin,
  PluginConnectionEvent,
  PluginFaderEvent,
  PluginMasterDeckEvent,
  PluginPlayStateEvent,
  PluginTrackEvent,
} from "./plugin-types.js";
import { TypedEventEmitter } from "../shared/typed-event-emitter.js";

/** Default virtual deck ID for single-deck plugins */
const VIRTUAL_DECK_ID = "1";

/** Suppress duplicate log messages within this window */
const LOG_DEDUP_WINDOW_MS = 60_000;

/** Heartbeat interval — emits 'heartbeat' event to keep bridge_last_seen fresh */
const HEARTBEAT_INTERVAL_MS = 120_000;

/** Auto-reconnect backoff constants */
const RECONNECT_INITIAL_MS = 2000;
const RECONNECT_MAX_MS = 30_000;
const RECONNECT_MULTIPLIER = 2;

interface PluginBridgeEventMap {
  deckLive: [event: DeckLiveEvent];
  connection: [event: PluginConnectionEvent];
  log: [message: string];
  error: [error: Error];
  clearNowPlaying: [];
  heartbeat: [];
  ready: [];
}

/**
 * PluginBridge connects an EquipmentSourcePlugin to a DeckStateManager,
 * translating plugin events and synthesizing missing data.
 *
 * Events emitted:
 *   'deckLive' - forwarded from DeckStateManager when a track goes live
 *   'connection' - forwarded from the plugin (connected/disconnected)
 *   'log' - diagnostic messages from both plugin and DeckStateManager
 *   'error' - errors from the plugin
 */
export class PluginBridge extends TypedEventEmitter<PluginBridgeEventMap> {
  private readonly plugin: EquipmentSourcePlugin;
  private deckManager: DeckStateManager;
  private readonly deckManagerConfig: DeckStateManagerConfig;
  private running = false;
  private startup: Promise<void> | null = null;
  private reconnecting: Promise<void> | null = null;
  private stopping: Promise<void> | null = null;
  private readonly recentLogs = new Map<string, number>();
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private wasConnected = false;
  private pluginConfig?: Record<string, unknown>;

  constructor(plugin: EquipmentSourcePlugin, config: DeckStateManagerConfig) {
    super();
    this.plugin = plugin;
    this.deckManagerConfig = { ...config };
    this.deckManager = new DeckStateManager(config);
  }

  get isRunning(): boolean {
    return this.running;
  }

  get pluginInfo() {
    return this.plugin.info;
  }

  get pluginId(): string {
    return this.plugin.info.id;
  }

  get pluginCapabilities() {
    return this.plugin.capabilities;
  }

  /** Return copied deck state for status consumers without exposing the manager. */
  getDeckStatusSnapshot(): DeckStatusSnapshot {
    const deckStates: DeckStateSnapshot[] = this.deckManager.getDeckIds().flatMap((deckId) => {
      const state = this.deckManager.findDeckState(deckId);
      return state ? [{ ...state, track: state.track ? { ...state.track } : null }] : [];
    });
    return { deckCount: deckStates.length, deckStates };
  }

  async start(pluginConfig?: Record<string, unknown>): Promise<void> {
    if (this.running || this.stopping) {
      throw new Error("PluginBridge is already running");
    }

    this.pluginConfig = pluginConfig;
    this.deckManager.destroy();
    this.deckManager = new DeckStateManager(this.deckManagerConfig);
    this.reconnectAttempt = 0;
    this.wasConnected = false;
    this.running = true;
    this.wireDeckManagerEvents();
    this.wirePluginEvents();

    const startup = Promise.resolve().then(() => this.plugin.start(pluginConfig));
    this.startup = startup;
    try {
      await startup;
      if (!this.running) {
        throw new Error("PluginBridge was stopped while starting");
      }
    } catch (err) {
      if (this.running) {
        this.running = false;
        this.cleanup();
      }
      throw err;
    } finally {
      if (this.startup === startup) this.startup = null;
    }
  }

  async stop(): Promise<void> {
    if (this.stopping) return this.stopping;
    if (!this.running && !this.startup) return;

    this.running = false;
    this.cancelReconnect();
    this.stopHeartbeat();

    const startup = this.startup;
    const reconnecting = this.reconnecting;
    this.stopping = this.finishStop(startup, reconnecting);
    try {
      await this.stopping;
    } finally {
      this.stopping = null;
    }
  }

  /** Reset all deck state and clear now-playing. */
  resetDecks(): void {
    this.deckManager.reset();
    this.emit("clearNowPlaying");
  }

  /** Cancel any pending reconnect timer and reconnect immediately. */
  async reconnect(): Promise<void> {
    this.cancelReconnect();
    await this.attemptReconnect();
  }

  /** Full restart: stop the bridge and start it again with optional new config. */
  async restart(pluginConfig?: Record<string, unknown>): Promise<void> {
    await this.stop();
    await this.start(pluginConfig ?? this.pluginConfig);
  }

  private cleanup(): void {
    this.cancelReconnect();
    this.stopHeartbeat();
    this.emit("clearNowPlaying");
    this.deckManager.destroy();
    this.plugin.removeAllListeners();
    this.recentLogs.clear();
  }

  private async finishStop(
    startup: Promise<void> | null,
    reconnecting: Promise<void> | null,
  ): Promise<void> {
    if (startup) await startup.catch(() => {});
    if (reconnecting) await reconnecting.catch(() => {});
    let stopError: unknown;
    let stopFailed = false;
    try {
      await this.plugin.stop();
    } catch (error) {
      stopFailed = true;
      stopError = error;
    }
    this.cleanup();
    if (stopFailed) throw stopError;
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => this.emit("heartbeat"), HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  /** Wire DeckStateManager events (called once per start). */
  private wireDeckManagerEvents(): void {
    this.deckManager.on("deckLive", (event: DeckLiveEvent) => {
      this.emit("deckLive", event);
    });

    this.deckManager.on("log", (message: string) => {
      this.emit("log", message);
    });

    this.deckManager.on("nowPlayingCleared", () => {
      this.emit("clearNowPlaying");
    });
  }

  /** Wire plugin events (called on start and on reconnect). */
  private wirePluginEvents(): void {
    this.plugin.on("track", (event: PluginTrackEvent) => {
      this.handleTrack(event);
    });

    this.plugin.on("playState", (event: PluginPlayStateEvent) => {
      this.handlePlayState(event);
    });

    this.plugin.on("fader", (event: PluginFaderEvent) => {
      this.handleFader(event);
    });

    this.plugin.on("masterDeck", (event: PluginMasterDeckEvent) => {
      this.handleMasterDeck(event);
    });

    this.plugin.on("connection", (event: PluginConnectionEvent) => {
      if (!this.running) return;
      if (event.connected) {
        this.wasConnected = true;
        this.reconnectAttempt = 0;
        this.startHeartbeat();
      } else {
        this.stopHeartbeat();
        this.emit("clearNowPlaying");
        if (this.wasConnected) {
          this.scheduleReconnect();
        }
      }
      this.emit("connection", event);
    });

    this.plugin.on("ready", () => {
      this.emit("ready");
    });

    this.plugin.on("log", (message: string) => {
      if (this.shouldThrottleLog(message)) return;
      this.emit("log", `[${this.plugin.info.id}] ${message}`);
    });

    this.plugin.on("error", (err: Error) => {
      this.emit("error", err);
    });
  }

  // --- Auto-reconnect ---

  private scheduleReconnect(): void {
    if (!this.running || this.reconnectTimer !== null) return;

    this.reconnectAttempt++;
    const delay = Math.min(
      RECONNECT_INITIAL_MS * Math.pow(RECONNECT_MULTIPLIER, this.reconnectAttempt - 1),
      RECONNECT_MAX_MS,
    );

    this.emit(
      "log",
      `Device disconnected — reconnecting in ${(delay / 1000).toFixed(0)}s (attempt ${this.reconnectAttempt})`,
    );

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.attemptReconnect();
    }, delay);
  }

  private async attemptReconnect(): Promise<void> {
    if (!this.running) return;
    if (this.reconnecting) return this.reconnecting;

    const reconnecting = this.performReconnect();
    this.reconnecting = reconnecting;
    try {
      await reconnecting;
    } finally {
      if (this.reconnecting === reconnecting) this.reconnecting = null;
    }
  }

  private async performReconnect(): Promise<void> {
    this.emit("log", `Reconnecting to ${this.plugin.info.name}...`);

    try {
      // Stop the old plugin instance (clean up stale resources)
      try {
        await this.plugin.stop();
      } catch {
        // Best effort
      }

      // stop() may have completed while plugin.stop() was awaiting network cleanup.
      if (!this.running) return;

      // Clear stale deck state from the old connection
      this.deckManager.reset();

      // Re-wire plugin events (old listeners removed by stop)
      this.plugin.removeAllListeners();
      this.wirePluginEvents();

      // Restart
      await this.plugin.start(this.pluginConfig);
      this.emit("log", `Reconnected to ${this.plugin.info.name} successfully`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.emit("log", `Reconnect failed: ${message}`);
      this.scheduleReconnect();
    }
  }

  private cancelReconnect(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectAttempt = 0;
  }

  /** Suppress duplicate log messages — only allow each unique message once per dedup window. */
  private shouldThrottleLog(message: string): boolean {
    const now = Date.now();
    const lastSeen = this.recentLogs.get(message);

    if (lastSeen !== undefined && now - lastSeen < LOG_DEDUP_WINDOW_MS) {
      return true;
    }

    this.recentLogs.set(message, now);

    // Prune stale entries periodically to prevent unbounded growth
    if (this.recentLogs.size > 200) {
      for (const [key, time] of this.recentLogs) {
        if (now - time >= LOG_DEDUP_WINDOW_MS) {
          this.recentLogs.delete(key);
        }
      }
    }

    return false;
  }

  private normalizeDeckId(deckId: string): string {
    if (!this.plugin.capabilities.multiDeck) {
      return VIRTUAL_DECK_ID;
    }
    return deckId;
  }

  /**
   * Check if a track is a duplicate of the current track on a deck.
   * Compares title and artist case-insensitively with trimmed whitespace.
   */
  private isTrackDuplicate(deckId: string, track: TrackInfo): boolean {
    const current = this.deckManager.getOrCreateDeckState(deckId).track;
    if (!current) return false;

    return (
      current.title.toLowerCase().trim() === track.title.toLowerCase().trim() &&
      current.artist.toLowerCase().trim() === track.artist.toLowerCase().trim()
    );
  }

  private handleTrack(event: PluginTrackEvent): void {
    const deckId = this.normalizeDeckId(event.deckId);

    // Skip duplicate track re-emissions (e.g. StageLinQ play-state changes)
    if (event.track !== null && this.isTrackDuplicate(deckId, event.track)) {
      return;
    }

    this.deckManager.updateTrackInfo(deckId, event.track);

    // Synthesize play state for plugins that lack it
    if (!this.plugin.capabilities.playState && event.track !== null) {
      this.deckManager.updatePlayState(deckId, true);
    }
  }

  private handlePlayState(event: PluginPlayStateEvent): void {
    const deckId = this.normalizeDeckId(event.deckId);
    this.deckManager.updatePlayState(deckId, event.isPlaying);
  }

  private handleFader(event: PluginFaderEvent): void {
    const deckId = this.normalizeDeckId(event.deckId);
    this.deckManager.updateFaderLevel(deckId, event.level);
  }

  private handleMasterDeck(event: PluginMasterDeckEvent): void {
    const deckId = this.normalizeDeckId(event.deckId);
    this.deckManager.setMasterDeck(deckId);
  }
}
