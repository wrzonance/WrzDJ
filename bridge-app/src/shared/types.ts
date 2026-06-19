/** Authentication state shared between main and renderer */
export interface AuthState {
  readonly isAuthenticated: boolean;
  readonly username: string | null;
  readonly apiUrl: string;
}

/** Bridge operational status */
export interface BridgeStatus {
  readonly isRunning: boolean;
  readonly connectedDevice: string | null;
  readonly eventCode: string | null;
  readonly eventName: string | null;
  readonly currentTrack: TrackDisplay | null;
  readonly deckStates: readonly DeckDisplay[];
  /** Reason the bridge was stopped automatically (e.g. event deleted/expired) */
  readonly stopReason: string | null;
  /** Whether the backend API is reachable (false after all retries exhausted) */
  readonly backendReachable: boolean;
  /** Network warnings (e.g. subnet conflicts) detected at bridge start */
  readonly networkWarnings: readonly string[];
  /** Circuit breaker state (CLOSED, OPEN, HALF_OPEN) */
  readonly circuitBreakerState: string;
  /** Number of tracks buffered for replay */
  readonly bufferSize: number;
  /** Number of active decks */
  readonly deckCount: number;
  /** Seconds since bridge was started */
  readonly uptimeSeconds: number;
  /** Active plugin ID (e.g. 'stagelinq', 'pioneer') */
  readonly pluginId: string | null;
}

/** Track info for display in the GUI */
export interface TrackDisplay {
  readonly title: string;
  readonly artist: string;
  readonly album: string | null;
  readonly deckId: string;
  readonly startedAt: number;
}

/** Per-deck display state */
export interface DeckDisplay {
  readonly deckId: string;
  readonly state: string;
  readonly trackTitle: string | null;
  readonly trackArtist: string | null;
  readonly isPlaying: boolean;
  readonly isMaster: boolean;
  readonly faderLevel: number;
}

/** Bridge detection settings */
export interface BridgeSettings {
  readonly protocol: string;
  readonly pluginConfig?: Record<string, unknown>;
  readonly liveThresholdSeconds: number;
  readonly pauseGraceSeconds: number;
  readonly nowPlayingPauseSeconds: number;
  readonly useFaderDetection: boolean;
  readonly masterDeckPriority: boolean;
  readonly minPlaySeconds: number;
}

/** Describes a user-configurable option exposed by a plugin */
export interface PluginConfigOption {
  readonly key: string;
  readonly label: string;
  readonly type: 'number' | 'string' | 'boolean';
  readonly default: number | string | boolean;
  readonly description?: string;
  readonly min?: number;
  readonly max?: number;
}

/** Plugin capabilities (what data it can provide) */
export interface PluginCapabilities {
  readonly multiDeck: boolean;
  readonly playState: boolean;
  readonly faderLevel: boolean;
  readonly masterDeck: boolean;
  readonly albumMetadata: boolean;
}

/** Serializable plugin metadata for IPC */
export interface PluginMeta {
  readonly info: { readonly id: string; readonly name: string; readonly description: string };
  readonly capabilities: PluginCapabilities;
  readonly configOptions: readonly PluginConfigOption[];
}

/** Event info from the backend */
export interface EventInfo {
  readonly id: number;
  /** Internal collection code — the identifier the bridge API resolves by. */
  readonly code: string;
  /** Live join code (QR target) — the code guests use and the DJ dashboard shows. */
  readonly joinCode: string;
  readonly name: string;
  readonly isActive: boolean;
  readonly expiresAt: string;
}

/** Config passed to BridgeRunner.start() */
export interface BridgeRunnerConfig {
  readonly apiUrl: string;
  readonly apiKey: string;
  readonly eventCode: string;
  readonly settings: BridgeSettings;
}

/** Log severity level (matches bridge Logger levels) */
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

/** Structured log message sent over IPC */
export interface IpcLogMessage {
  readonly message: string;
  readonly level: LogLevel;
}

/** IPC channel names */
export const IPC_CHANNELS = {
  AUTH_LOGIN: 'auth:login',
  AUTH_LOGOUT: 'auth:logout',
  AUTH_GET_STATE: 'auth:getState',
  AUTH_CHANGED: 'auth:changed',
  EVENTS_FETCH: 'events:fetch',
  PLUGINS_LIST_META: 'plugins:listMeta',
  BRIDGE_START: 'bridge:start',
  BRIDGE_STOP: 'bridge:stop',
  BRIDGE_STATUS: 'bridge:status',
  BRIDGE_LOG: 'bridge:log',
  SETTINGS_GET: 'settings:get',
  SETTINGS_UPDATE: 'settings:update',
  BRIDGE_EXPORT_DEBUG_REPORT: 'bridge:exportDebugReport',
  BRIDGE_RESET_DECKS: 'bridge:resetDecks',
  BRIDGE_RECONNECT: 'bridge:reconnect',
  BRIDGE_RESTART: 'bridge:restart',
  BRIDGE_PING: 'bridge:ping',
} as const;

/** Default bridge settings (fader off for 3rd-party mixer compat, master deck priority off) */
export const DEFAULT_SETTINGS: BridgeSettings = {
  protocol: 'stagelinq',
  liveThresholdSeconds: 15,
  pauseGraceSeconds: 3,
  nowPlayingPauseSeconds: 10,
  useFaderDetection: false,
  masterDeckPriority: false,
  minPlaySeconds: 5,
};
