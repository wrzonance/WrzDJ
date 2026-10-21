import type {
  AuthState,
  BridgeSettings,
  BridgeStatus,
  EventInfo,
  IpcLogMessage,
  PluginMeta,
} from './types.js';

/** Public API exposed to the renderer by the preload script. */
export interface BridgeApi {
  login(apiUrl: string, username: string, password: string): Promise<void>;
  logout(): Promise<void>;
  getAuthState(): Promise<AuthState>;
  listPluginMeta(): Promise<readonly PluginMeta[]>;
  fetchEvents(): Promise<readonly EventInfo[]>;
  startBridge(eventCode: string): Promise<void>;
  stopBridge(): Promise<void>;
  getSettings(): Promise<BridgeSettings>;
  updateSettings(settings: Partial<BridgeSettings>): Promise<BridgeSettings>;
  resetDecks(): Promise<void>;
  reconnect(): Promise<void>;
  restartBridge(): Promise<void>;
  exportDebugReport(): Promise<string | null>;
  onBridgeStatus(callback: (status: BridgeStatus) => void): () => void;
  onBridgeLog(callback: (logMessage: IpcLogMessage) => void): () => void;
  onPing(callback: () => void): () => void;
  onAuthChanged(callback: (state: AuthState) => void): () => void;
}
