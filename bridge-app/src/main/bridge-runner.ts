/**
 * BridgeRunner wraps the PluginBridge for GUI lifecycle control.
 * Delegates equipment detection to the configured plugin via the plugin system.
 *
 * Features:
 *   - AbortController timeouts on all fetch requests
 *   - Circuit breaker to avoid hammering an unreachable backend
 *   - Retry logic on DELETE (clearNowPlaying)
 *   - 401 detection: stops bridge on token expiry
 */
import { EventEmitter } from 'events';
import { PluginBridge } from '@bridge/plugin-bridge.js';
import { getPlugin } from '@bridge/plugin-registry.js';
import { CircuitBreaker } from '@bridge/circuit-breaker.js';
import { CommandPoller } from '@bridge/command-poller.js';
import type { BridgeCommand } from '@bridge/command-poller.js';
import { Logger, type LogLevel } from '@bridge/logger.js';
import { TrackHistoryBuffer } from '@bridge/track-history-buffer.js';
import type { DeckLiveEvent, DeckState } from '@bridge/deck-state.js';
import type { NowPlayingPayload, BridgeStatusPayload } from '@bridge/types.js';
import type { PluginConnectionEvent } from '@bridge/plugin-types.js';
import { checkEventHealth } from './event-health-service.js';
import { detectSubnetConflicts, formatConflictWarnings } from './network-check.js';
import type { BridgeRunnerConfig, BridgeStatus, DeckDisplay, IpcLogMessage, TrackDisplay } from '../shared/types.js';

// Register built-in plugins
import '@bridge/plugins/index.js';

const MAX_RETRIES = 3;
const INITIAL_BACKOFF_MS = 2000;
const FETCH_TIMEOUT_MS = 10_000;
const DELETE_MAX_RETRIES = 2;
const DELETE_BACKOFF_MS = 1000;
const HEALTH_CHECK_INTERVAL_MS = 30_000;

/**
 * BridgeRunner manages the lifecycle of the bridge via plugins.
 *
 * Events:
 *   'statusChanged' - emitted whenever bridge status changes (for IPC forwarding)
 *   'log' - emitted with log messages for the GUI console
 */
export class BridgeRunner extends EventEmitter {
  private pluginBridge: PluginBridge | null = null;
  private config: BridgeRunnerConfig | null = null;
  private running = false;
  private connectedDevice: string | null = null;
  private currentTrack: TrackDisplay | null = null;
  private lastTrackKey: string | null = null;
  private lastPostTime = 0;
  private healthCheckTimer: ReturnType<typeof setInterval> | null = null;
  private stopReason: string | null = null;
  private networkWarnings: string[] = [];
  private backendReachable = true;
  private startedAt: number | null = null;
  private circuitBreaker = new CircuitBreaker({ failureThreshold: 3, cooldownMs: 60_000 });
  private commandPoller: CommandPoller | null = null;
  private readonly logger = new Logger('Bridge');
  private readonly trackBuffer = new TrackHistoryBuffer();

  constructor() {
    super();
    this.wireCircuitBreaker();
  }

  get isRunning(): boolean {
    return this.running;
  }

  async start(config: BridgeRunnerConfig): Promise<void> {
    if (this.running) {
      throw new Error('Bridge is already running');
    }

    this.config = config;
    this.running = true;
    this.startedAt = Date.now();
    this.lastTrackKey = null;
    this.lastPostTime = 0;
    this.currentTrack = null;
    this.connectedDevice = null;
    this.stopReason = null;
    this.networkWarnings = [];
    this.backendReachable = true;
    this.circuitBreaker.reset();
    this.trackBuffer.clear();

    const protocol = config.settings.protocol || 'stagelinq';

    this.log(`Starting bridge for event ${config.eventCode}...`);
    this.log(`API URL: ${config.apiUrl}`);
    this.log(`Protocol: ${protocol}`);
    this.log(`Live Threshold: ${config.settings.liveThresholdSeconds}s`);
    this.log(`Fader Detection: ${config.settings.useFaderDetection}`);
    this.log(`Master Deck Priority: ${config.settings.masterDeckPriority}`);

    // Check for network interface conflicts (affects broadcast-based protocols)
    const conflicts = detectSubnetConflicts();
    if (conflicts.length > 0) {
      this.networkWarnings = formatConflictWarnings(conflicts);
      for (const warning of this.networkWarnings) {
        this.log(warning, 'warn');
      }
    }

    // Create the plugin
    const plugin = getPlugin(protocol);
    if (!plugin) {
      this.running = false;
      const err = new Error(`Unknown protocol "${protocol}"`);
      this.log(err.message);
      this.emitStatus();
      throw err;
    }

    // Create the PluginBridge
    this.pluginBridge = new PluginBridge(plugin, {
      liveThresholdSeconds: config.settings.liveThresholdSeconds,
      pauseGraceSeconds: config.settings.pauseGraceSeconds,
      nowPlayingPauseSeconds: config.settings.nowPlayingPauseSeconds,
      useFaderDetection: config.settings.useFaderDetection,
      masterDeckPriority: config.settings.masterDeckPriority,
    });

    this.wireEvents();
    this.emitStatus();

    try {
      await this.pluginBridge.start(config.settings.pluginConfig);
      this.log('Plugin started, listening for DJ equipment...');
      this.startHealthCheck();
      this.startCommandPoller();

      // Immediate handshake — tell the backend we're online and listening
      this.log('Bridge online — sending initial status to backend');
      await this.postBridgeStatus(true);
    } catch (err) {
      this.running = false;
      this.pluginBridge = null;
      const message = err instanceof Error ? err.message : String(err);
      this.log(`Failed to connect: ${message}`, 'error');
      this.emitStatus();
      throw err;
    }
  }

  async stop(reason?: string): Promise<void> {
    if (!this.running) return;

    this.stopHealthCheck();
    this.stopCommandPoller();

    if (reason) {
      this.stopReason = reason;
      this.log(`Stopping bridge: ${reason}`);
    } else {
      this.log('Stopping bridge...');
    }

    this.running = false;

    if (this.pluginBridge) {
      await this.pluginBridge.stop();
      this.pluginBridge = null;
    }

    try {
      await this.clearNowPlaying();
      await this.postBridgeStatus(false);
    } catch {
      // Best effort on shutdown
    }

    this.connectedDevice = null;
    this.currentTrack = null;
    this.emitStatus();
    this.log('Bridge stopped.');
  }

  getStatus(): BridgeStatus {
    const deckStates: DeckDisplay[] = [];

    if (this.pluginBridge) {
      const manager = this.pluginBridge.manager;
      for (const deckId of manager.getDeckIds()) {
        const state: DeckState = manager.getDeckState(deckId);
        if (state.state === 'EMPTY' && !state.track) continue;
        deckStates.push({
          deckId: state.deckId,
          state: state.state,
          trackTitle: state.track?.title ?? null,
          trackArtist: state.track?.artist ?? null,
          isPlaying: state.isPlaying,
          isMaster: state.isMaster,
          faderLevel: state.faderLevel,
        });
      }
    }

    return {
      isRunning: this.running,
      connectedDevice: this.connectedDevice,
      eventCode: this.config?.eventCode ?? null,
      eventName: null,
      currentTrack: this.currentTrack,
      deckStates,
      backendReachable: this.backendReachable,
      stopReason: this.stopReason,
      networkWarnings: this.networkWarnings,
      circuitBreakerState: this.circuitBreaker.getState(),
      bufferSize: this.trackBuffer.size,
      deckCount: deckStates.length,
      uptimeSeconds: this.startedAt !== null ? Math.floor((Date.now() - this.startedAt) / 1000) : 0,
      pluginId: this.pluginBridge?.pluginId ?? null,
    };
  }

  private wireCircuitBreaker(): void {
    this.circuitBreaker.on('stateChange', ({ from, to }: { from: string; to: string }) => {
      if (to === 'OPEN') {
        this.log('Circuit breaker OPEN — backend unreachable, pausing API calls for 60s', 'error');
        if (this.backendReachable) {
          this.backendReachable = false;
          this.emitStatus();
        }
      } else if (to === 'HALF_OPEN') {
        this.log('Circuit breaker HALF_OPEN — probing backend...');
      } else if (to === 'CLOSED' && from !== 'CLOSED') {
        this.log('Circuit breaker CLOSED — backend recovered');
        if (!this.backendReachable) {
          this.backendReachable = true;
          this.emitStatus();
        }
        this.replayBufferedTracks();
      }
    });
  }

  private wireEvents(): void {
    if (!this.pluginBridge) return;

    // Handle track going "live"
    this.pluginBridge.on('deckLive', async (event: DeckLiveEvent) => {
      const { deckId, track } = event;

      if (this.shouldSkipTrack(track.artist, track.title)) return;

      this.log(`Deck ${deckId} LIVE: "${track.title}" by ${track.artist}`);

      this.updateLastTrack(track.artist, track.title);
      this.currentTrack = {
        title: track.title,
        artist: track.artist,
        album: track.album ?? null,
        deckId,
        startedAt: Date.now(),
      };

      this.emitStatus();
      await this.postNowPlaying(track.title, track.artist, track.album, deckId, this.pluginBridge!.pluginId);
    });

    // Handle connection status from plugin
    this.pluginBridge.on('connection', async (event: PluginConnectionEvent) => {
      if (event.connected) {
        this.connectedDevice = event.deviceName ?? 'Unknown Device';
        this.log(`Device connected: ${this.connectedDevice}`);
        this.emitStatus();
        await this.postBridgeStatus(true, this.connectedDevice);
      } else {
        this.connectedDevice = null;
        this.log('Device disconnected');
        this.emitStatus();
        await this.postBridgeStatus(false);
      }
    });

    // Handle heartbeat — keep bridge_last_seen fresh on the backend
    this.pluginBridge.on('heartbeat', async () => {
      await this.postBridgeStatus(true, this.connectedDevice ?? undefined);
    });

    // Handle authoritative now-playing clear
    this.pluginBridge.on('clearNowPlaying', async () => {
      this.currentTrack = null;
      this.emitStatus();
      await this.clearNowPlaying();
    });

    // Forward plugin ready
    this.pluginBridge.on('ready', () => {
      this.log('All devices ready — listening for tracks');
    });

    // Forward logs
    this.pluginBridge.on('log', (message: string) => {
      this.log(message);
    });

    // Forward status updates when deck state changes
    this.pluginBridge.manager.on('log', () => {
      this.emitStatus();
    });
  }

  // --- Track deduplication ---

  private makeTrackKey(artist: string, title: string): string {
    return `${artist.toLowerCase().trim()}::${title.toLowerCase().trim()}`;
  }

  private shouldSkipTrack(artist: string, title: string): boolean {
    if (!title) return true;

    const key = this.makeTrackKey(artist, title);
    if (key === this.lastTrackKey) return true;

    const now = Date.now();
    if (this.config && now - this.lastPostTime < this.config.settings.minPlaySeconds * 1000) {
      this.log(`Debouncing track change (${now - this.lastPostTime}ms since last)`, 'debug');
      return true;
    }

    return false;
  }

  private updateLastTrack(artist: string, title: string): void {
    this.lastTrackKey = this.makeTrackKey(artist, title);
    this.lastPostTime = Date.now();
  }

  // --- HTTP communication ---

  /**
   * Make a fetch request with an AbortController timeout.
   */
  private async fetchWithTimeout(
    url: string,
    options: RequestInit,
    timeoutMs: number = FETCH_TIMEOUT_MS,
  ): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * POST with retry logic and circuit breaker.
   * Returns true if successful, false on failure.
   * Stops bridge on 401 (token expiry).
   */
  private async postWithRetry(
    endpoint: string,
    payload: NowPlayingPayload | BridgeStatusPayload,
  ): Promise<boolean> {
    if (!this.config) return false;

    if (!this.circuitBreaker.allowRequest()) {
      this.log(`POST ${endpoint} skipped — circuit breaker OPEN`, 'warn');
      return false;
    }

    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const response = await this.fetchWithTimeout(`${this.config.apiUrl}${endpoint}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Bridge-API-Key': this.config.apiKey,
          },
          body: JSON.stringify(payload),
        });

        if (response.status === 401) {
          // 401 is an auth problem, not a backend availability issue — don't count as circuit failure
          this.log(`POST ${endpoint} returned 401 — session expired`, 'error');
          // Stop bridge asynchronously (don't block the retry loop)
          setTimeout(() => {
            this.stop('Session expired — please log in again');
          }, 0);
          return false;
        }

        if (!response.ok) {
          const text = await response.text();
          throw new Error(`HTTP ${response.status}: ${text}`);
        }

        if (!this.backendReachable) {
          this.backendReachable = true;
          this.emitStatus();
        }
        this.circuitBreaker.recordSuccess();
        this.log(`POST ${endpoint} succeeded`);
        return true;
      } catch (err) {
        lastError = err as Error;
        if (attempt < MAX_RETRIES) {
          const backoff = INITIAL_BACKOFF_MS * Math.pow(2, attempt);
          this.log(`Retry ${attempt + 1}/${MAX_RETRIES} in ${backoff}ms: ${lastError.message}`, 'warn');
          await new Promise((resolve) => setTimeout(resolve, backoff));
        }
      }
    }

    this.circuitBreaker.recordFailure();
    if (this.backendReachable) {
      this.backendReachable = false;
      this.emitStatus();
    }
    this.log(`POST ${endpoint} failed after ${MAX_RETRIES + 1} attempts: ${lastError?.message}`, 'error');
    return false;
  }

  private async postNowPlaying(
    title: string,
    artist: string,
    album?: string,
    deck?: string,
    source?: string,
  ): Promise<void> {
    if (!this.config) return;

    const payload: NowPlayingPayload = {
      event_code: this.config.eventCode,
      title,
      artist,
      album: album ?? null,
      deck: deck ?? null,
      source: source ?? null,
    };

    const success = await this.postWithRetry('/api/bridge/nowplaying', payload);
    if (!success) {
      this.trackBuffer.push(payload);
      this.log(`Buffered track for replay (${this.trackBuffer.size} in buffer)`);
    }
  }

  private async postBridgeStatus(connected: boolean, deviceName?: string): Promise<void> {
    if (!this.config) return;

    const deckCount = this.pluginBridge
      ? this.pluginBridge.manager.getDeckIds().length
      : 0;

    const payload: BridgeStatusPayload = {
      event_code: this.config.eventCode,
      connected,
      device_name: deviceName ?? null,
      circuit_breaker_state: this.circuitBreaker.getState(),
      buffer_size: this.trackBuffer.size,
      plugin_id: this.pluginBridge?.pluginId ?? null,
      deck_count: deckCount,
      uptime_seconds: this.startedAt !== null
        ? Math.floor((Date.now() - this.startedAt) / 1000)
        : null,
    };

    await this.postWithRetry('/api/bridge/status', payload);
  }

  /**
   * Clear now-playing on the backend with retry logic.
   */
  private async clearNowPlaying(): Promise<void> {
    if (!this.config) return;

    const endpoint = `/api/bridge/nowplaying/${this.config.eventCode}`;

    for (let attempt = 0; attempt <= DELETE_MAX_RETRIES; attempt++) {
      try {
        const response = await this.fetchWithTimeout(`${this.config.apiUrl}${endpoint}`, {
          method: 'DELETE',
          headers: {
            'X-Bridge-API-Key': this.config.apiKey,
          },
        });

        if (!response.ok) {
          const text = await response.text();
          throw new Error(`HTTP ${response.status}: ${text}`);
        }

        this.log(`DELETE ${endpoint} succeeded`);
        return;
      } catch (err) {
        const message = (err as Error).message;
        if (attempt < DELETE_MAX_RETRIES) {
          const backoff = DELETE_BACKOFF_MS * Math.pow(2, attempt);
          this.log(`DELETE ${endpoint} retry ${attempt + 1}/${DELETE_MAX_RETRIES} in ${backoff}ms: ${message}`, 'warn');
          await new Promise((resolve) => setTimeout(resolve, backoff));
        } else {
          this.log(`DELETE ${endpoint} failed after ${DELETE_MAX_RETRIES + 1} attempts: ${message}`, 'error');
        }
      }
    }
  }

  // --- Event health check ---

  private startHealthCheck(): void {
    this.stopHealthCheck();
    this.healthCheckTimer = setInterval(() => {
      this.runHealthCheck();
    }, HEALTH_CHECK_INTERVAL_MS);
  }

  private stopHealthCheck(): void {
    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer);
      this.healthCheckTimer = null;
    }
  }

  private async runHealthCheck(): Promise<void> {
    if (!this.running || !this.config) return;

    const status = await checkEventHealth(this.config.apiUrl, this.config.eventCode);

    if (status === 'not_found') {
      this.log('Event no longer exists — stopping bridge');
      await this.stop('Event was deleted');
    } else if (status === 'expired') {
      this.log('Event has expired or been archived — stopping bridge');
      await this.stop('Event expired or archived');
    }
    // 'active' and 'error' — do nothing (don't stop on transient errors)
  }

  // --- Track buffer replay ---

  private replayBufferedTracks(): void {
    const tracks = this.trackBuffer.drain();
    if (tracks.length === 0) return;

    this.log(`Replaying ${tracks.length} buffered track(s)...`);

    // Replay asynchronously — don't block the circuit breaker handler
    (async () => {
      for (const { payload } of tracks) {
        const replayPayload: NowPlayingPayload = { ...payload, delayed: true };
        const success = await this.postWithRetry('/api/bridge/nowplaying', replayPayload);
        if (!success) {
          this.log(`Replay failed for "${payload.title}" — backend may be down again`, 'warn');
          return;
        }
        this.log(`Replayed: "${payload.title}" by ${payload.artist}`);
      }
    })();
  }

  // --- Admin commands ---

  async resetDecks(): Promise<void> {
    if (!this.running || !this.pluginBridge) {
      this.log('Cannot reset decks — bridge is not running', 'warn');
      return;
    }
    this.log('Resetting deck states...');
    this.pluginBridge.resetDecks();
    this.emitStatus();
  }

  async reconnect(): Promise<void> {
    if (!this.running || !this.pluginBridge) {
      this.log('Cannot reconnect — bridge is not running', 'warn');
      return;
    }
    this.log('Reconnecting to DJ equipment...');
    await this.pluginBridge.reconnect();
  }

  async restartBridge(): Promise<void> {
    if (!this.config) {
      this.log('Cannot restart — no config available', 'warn');
      return;
    }
    this.log('Restarting bridge...');
    const config = this.config;
    await this.stop();
    await this.start(config);
  }

  // --- Command poller ---

  private startCommandPoller(): void {
    if (!this.config) return;
    this.commandPoller = new CommandPoller(this.circuitBreaker, this.logger);
    this.commandPoller.on('command', (type: string, command?: BridgeCommand) => {
      this.handleCommand(type, command);
    });
    this.commandPoller.start(this.config.apiUrl, this.config.apiKey, this.config.eventCode);
  }

  private stopCommandPoller(): void {
    if (this.commandPoller) {
      this.commandPoller.stop();
      this.commandPoller = null;
    }
  }

  private handleCommand(type: string, command?: BridgeCommand): void {
    switch (type) {
      case 'ping':
        this.log('Ping received from dashboard');
        this.emit('ping');
        break;
      case 'reset_decks':
        this.resetDecks();
        break;
      case 'reconnect':
        this.reconnect();
        break;
      case 'restart':
        this.restartBridge();
        break;
      case 'setbuilder_transport':
        this.handleSetbuilderTransport(command?.payload ?? {});
        break;
      default:
        this.log(`Unknown command: ${type}`, 'warn');
    }
  }

  private handleSetbuilderTransport(payload: Record<string, unknown>): void {
    const action = typeof payload.action === 'string' ? payload.action : 'unknown';
    const title = typeof payload.title === 'string' ? payload.title : '';
    const position = typeof payload.position_sec === 'number' ? payload.position_sec : 0;

    this.log(
      `Setbuilder transport command received: ${action}${title ? ` "${title}"` : ''} @ ${position.toFixed(1)}s`
    );
  }

  // --- Status emission ---

  private emitStatus(): void {
    this.emit('statusChanged', this.getStatus());
  }

  private log(message: string, level: LogLevel = 'info'): void {
    this.logger[level](message);
    const logMessage: IpcLogMessage = { message, level };
    this.emit('log', logMessage);
  }
}
