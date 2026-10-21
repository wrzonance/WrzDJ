/** Electron adapter for the shared bridge session runtime. */
import { EventEmitter } from 'events';
import {
  BridgeRuntime,
  getPlugin,
  Logger,
  type BridgeConfig,
  type DeckState,
  type LogLevel,
} from '@wrzdj/bridge/electron';
import { checkEventHealth } from './event-health-service.js';
import { detectSubnetConflicts, formatConflictWarnings } from './network-check.js';
import type { BridgeRunnerConfig, BridgeStatus, DeckDisplay, IpcLogMessage, TrackDisplay } from '../shared/types.js';

const HEALTH_CHECK_INTERVAL_MS = 30_000;
const MILLISECONDS_PER_SECOND = 1_000;

/** Maps the shared session runtime to Electron's established status and event contract. */
export class BridgeRunner extends EventEmitter {
  private runtime: BridgeRuntime | null = null;
  private config: BridgeRunnerConfig | null = null;
  private running = false;
  private connectedDevice: string | null = null;
  private currentTrack: TrackDisplay | null = null;
  private stopReason: string | null = null;
  private networkWarnings: string[] = [];
  private backendReachable = true;
  private startedAt: number | null = null;
  private healthCheckTimer: ReturnType<typeof setInterval> | null = null;
  private sessionGeneration = 0;
  private stopPromise: Promise<void> | null = null;
  private detachRuntimeEvents: (() => void) | null = null;
  private readonly logger = new Logger('Bridge');

  get isRunning(): boolean {
    return this.running;
  }

  async start(config: BridgeRunnerConfig): Promise<void> {
    let generation: number;
    const pendingStop = this.stopPromise;
    if (pendingStop) {
      generation = ++this.sessionGeneration;
      await pendingStop;
      if (generation !== this.sessionGeneration) {
        throw new Error('Bridge start was cancelled because the session changed');
      }
    } else {
      if (this.running) throw new Error('Bridge is already running');
      generation = ++this.sessionGeneration;
    }
    if (this.running) throw new Error('Bridge is already running');

    this.config = config;
    this.running = true;
    this.startedAt = Date.now();
    this.currentTrack = null;
    this.connectedDevice = null;
    this.stopReason = null;
    this.backendReachable = true;
    this.networkWarnings = [];

    const protocol = config.settings.protocol || 'stagelinq';
    this.log(`Starting bridge for event ${config.eventCode}...`);
    this.log(`API URL: ${config.apiUrl}`);
    this.log(`Protocol: ${protocol}`);
    this.log(`Live Threshold: ${config.settings.liveThresholdSeconds}s`);
    this.log(`Fader Detection: ${config.settings.useFaderDetection}`);
    this.log(`Master Deck Priority: ${config.settings.masterDeckPriority}`);

    const conflicts = detectSubnetConflicts();
    if (conflicts.length > 0) {
      this.networkWarnings = formatConflictWarnings(conflicts);
      for (const warning of this.networkWarnings) this.log(warning, 'warn');
    }

    const plugin = getPlugin(protocol);
    if (!plugin) {
      this.running = false;
      const error = new Error(`Unknown protocol "${protocol}"`);
      this.log(error.message, 'error');
      this.emitStatus();
      throw error;
    }

    const runtime = new BridgeRuntime(this.toBridgeConfig(config), plugin, { stopOnUnauthorized: true });
    this.runtime = runtime;
    this.detachRuntimeEvents = this.wireRuntimeEvents(runtime, generation);
    this.emitStatus();
    try {
      await runtime.start(config.settings.pluginConfig);
      if (!this.isCurrentSession(runtime, generation)) {
        await runtime.stop();
        return;
      }
      this.log('Plugin started, listening for DJ equipment...');
      this.startHealthCheck();
      this.emitStatus();
    } catch (error) {
      if (this.isCurrentSession(runtime, generation)) {
        this.running = false;
        this.runtime = null;
        this.detachRuntimeEvents?.();
        this.detachRuntimeEvents = null;
        this.log(`Failed to connect: ${error instanceof Error ? error.message : String(error)}`, 'error');
        this.emitStatus();
      }
      throw error;
    }
  }

  async stop(reason?: string): Promise<void> {
    ++this.sessionGeneration;
    if (this.stopPromise) return this.stopPromise;
    if (!this.running && !this.runtime) return;
    this.stopHealthCheck();
    if (reason) {
      this.stopReason = reason;
      this.log(`Stopping bridge: ${reason}`);
    } else {
      this.log('Stopping bridge...');
    }
    this.running = false;
    const runtime = this.runtime;
    this.runtime = null;
    this.detachRuntimeEvents?.();
    this.detachRuntimeEvents = null;
    const stopping = (async () => {
      try {
        await runtime?.stop();
      } catch (error) {
        this.log(`Bridge shutdown failed: ${error instanceof Error ? error.message : String(error)}`, 'error');
        throw error;
      } finally {
        this.connectedDevice = null;
        this.currentTrack = null;
        this.emitStatus();
      }
      this.log('Bridge stopped.');
    })();
    this.stopPromise = stopping;
    try {
      await stopping;
    } finally {
      if (this.stopPromise === stopping) this.stopPromise = null;
    }
  }

  getStatus(): BridgeStatus {
    const snapshot = this.runtime?.getSnapshot();
    const deckStates = (snapshot?.deckStates ?? []).flatMap((state) => this.toDeckDisplay(state));
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
      circuitBreakerState: snapshot?.circuitBreakerState ?? ('CLOSED' as const),
      bufferSize: snapshot?.bufferSize ?? 0,
      deckCount: deckStates.length,
      uptimeSeconds: this.startedAt === null
        ? 0
        : Math.floor((Date.now() - this.startedAt) / MILLISECONDS_PER_SECOND),
      pluginId: snapshot?.pluginId ?? null,
    };
  }

  resetDecks(): void {
    if (!this.running || !this.runtime) {
      this.log('Cannot reset decks — bridge is not running', 'warn');
      return;
    }
    this.log('Resetting deck states...');
    this.runtime.resetDecks();
  }

  async reconnect(): Promise<void> {
    if (!this.running || !this.runtime) {
      this.log('Cannot reconnect — bridge is not running', 'warn');
      return;
    }
    this.log('Reconnecting to DJ equipment...');
    await this.runtime.reconnect();
  }

  async restartBridge(): Promise<void> {
    if (!this.config) {
      this.log('Cannot restart — no config available', 'warn');
      return;
    }
    const config = this.config;
    const restartGeneration = this.sessionGeneration;
    this.log('Restarting bridge...');
    await this.stop();
    if (this.sessionGeneration !== restartGeneration + 1) {
      throw new Error('Bridge restart was cancelled because the session changed');
    }
    await this.start(config);
  }

  private toBridgeConfig(config: BridgeRunnerConfig): BridgeConfig {
    return {
      apiUrl: config.apiUrl,
      apiKey: config.apiKey,
      eventCode: config.eventCode,
      plugin: config.settings.protocol || 'stagelinq',
      minPlaySeconds: config.settings.minPlaySeconds,
      liveThresholdSeconds: config.settings.liveThresholdSeconds,
      nowPlayingPauseSeconds: config.settings.nowPlayingPauseSeconds,
      pauseGraceSeconds: config.settings.pauseGraceSeconds,
      useFaderDetection: config.settings.useFaderDetection,
      masterDeckPriority: config.settings.masterDeckPriority,
    };
  }

  private wireRuntimeEvents(runtime: BridgeRuntime, generation: number): () => void {
    const isCurrent = () => this.isCurrentSession(runtime, generation);
    const statusChanged = (snapshot: ReturnType<BridgeRuntime['getSnapshot']>) => {
      if (!isCurrent()) return;
      this.backendReachable = snapshot.backendReachable;
      this.emitStatus();
    };
    const connection = (event: { connected: boolean; deviceName?: string }) => {
      if (!isCurrent()) return;
      this.connectedDevice = event.connected ? event.deviceName ?? 'Unknown Device' : null;
      this.log(event.connected ? `Device connected: ${this.connectedDevice}` : 'Device disconnected');
      this.emitStatus();
    };
    const deckLive = (event: { deckId: string; track: { title: string; artist: string; album?: string } }) => {
      if (!isCurrent()) return;
      this.currentTrack = {
        title: event.track.title,
        artist: event.track.artist,
        album: event.track.album ?? null,
        deckId: event.deckId,
        startedAt: Date.now(),
      };
      this.log(`Deck ${event.deckId} LIVE: "${event.track.title}" by ${event.track.artist}`);
      this.emitStatus();
    };
    const clearNowPlaying = () => {
      if (!isCurrent()) return;
      this.currentTrack = null;
      this.emitStatus();
    };
    const ping = () => { if (isCurrent()) this.emit('ping'); };
    const authenticationError = () => {
      if (!isCurrent()) return;
      setTimeout(() => {
        if (isCurrent()) {
          void this.stop('Session expired — please log in again').catch((error: unknown) => {
            this.log(`Automatic bridge shutdown failed: ${error instanceof Error ? error.message : String(error)}`, 'error');
          });
        }
      }, 0);
    };
    const log = (message: IpcLogMessage) => { if (isCurrent()) this.forwardLog(message); };
    const equipmentError = (error: Error) => { if (isCurrent()) this.log(`Equipment error: ${error.message}`, 'error'); };
    runtime.on('statusChanged', statusChanged);
    runtime.on('connection', connection);
    runtime.on('deckLive', deckLive);
    runtime.on('clearNowPlaying', clearNowPlaying);
    runtime.on('ping', ping);
    runtime.on('authenticationError', authenticationError);
    runtime.on('log', log);
    runtime.on('equipmentError', equipmentError);
    return () => {
      runtime.off('statusChanged', statusChanged);
      runtime.off('connection', connection);
      runtime.off('deckLive', deckLive);
      runtime.off('clearNowPlaying', clearNowPlaying);
      runtime.off('ping', ping);
      runtime.off('authenticationError', authenticationError);
      runtime.off('log', log);
      runtime.off('equipmentError', equipmentError);
    };
  }

  private toDeckDisplay(state: DeckState): DeckDisplay[] {
    if (state.state === 'EMPTY' && !state.track) return [];
    return [{
      deckId: state.deckId,
      state: state.state,
      trackTitle: state.track?.title ?? null,
      trackArtist: state.track?.artist ?? null,
      isPlaying: state.isPlaying,
      isMaster: state.isMaster,
      faderLevel: state.faderLevel,
    }];
  }

  private startHealthCheck(): void {
    this.stopHealthCheck();
    this.healthCheckTimer = setInterval(() => {
      void this.runHealthCheck().catch((error: unknown) => {
        this.log(`Event health check failed: ${error instanceof Error ? error.message : String(error)}`, 'error');
      });
    }, HEALTH_CHECK_INTERVAL_MS);
  }

  private stopHealthCheck(): void {
    if (this.healthCheckTimer !== null) {
      clearInterval(this.healthCheckTimer);
      this.healthCheckTimer = null;
    }
  }

  private async runHealthCheck(): Promise<void> {
    if (!this.running || !this.config) return;
    const runtime = this.runtime;
    const generation = this.sessionGeneration;
    const status = await checkEventHealth(this.config.apiUrl, this.config.eventCode);
    if (!runtime || !this.isCurrentSession(runtime, generation)) return;
    if (status === 'not_found') await this.stop('Event was deleted');
    else if (status === 'expired') await this.stop('Event expired or archived');
  }

  private isCurrentSession(runtime: BridgeRuntime, generation: number): boolean {
    return this.running && this.runtime === runtime && this.sessionGeneration === generation;
  }

  private emitStatus(): void {
    this.emit('statusChanged', this.getStatus());
  }

  private forwardLog(message: IpcLogMessage): void {
    this.logger[message.level](message.message);
    this.emit('log', message);
  }

  private log(message: string, level: LogLevel = 'info'): void {
    this.forwardLog({ message, level });
  }
}
