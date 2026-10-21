import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';
import type { AuthState, BridgeSettings, BridgeStatus, EventInfo, IpcLogMessage, PluginMeta } from '../shared/types.js';
import type { BridgeApi } from '../shared/bridge-api.js';
import { IPC_CHANNELS } from '../shared/types.js';

const bridgeApi = {
  // Auth
  login: (apiUrl: string, username: string, password: string): Promise<void> =>
    ipcRenderer.invoke(IPC_CHANNELS.AUTH_LOGIN, apiUrl, username, password),

  logout: (): Promise<void> =>
    ipcRenderer.invoke(IPC_CHANNELS.AUTH_LOGOUT),

  getAuthState: (): Promise<AuthState> =>
    ipcRenderer.invoke(IPC_CHANNELS.AUTH_GET_STATE),

  // Plugins
  listPluginMeta: (): Promise<readonly PluginMeta[]> =>
    ipcRenderer.invoke(IPC_CHANNELS.PLUGINS_LIST_META),

  // Events
  fetchEvents: (): Promise<readonly EventInfo[]> =>
    ipcRenderer.invoke(IPC_CHANNELS.EVENTS_FETCH),

  // Bridge control
  startBridge: (eventCode: string): Promise<void> =>
    ipcRenderer.invoke(IPC_CHANNELS.BRIDGE_START, eventCode),

  stopBridge: (): Promise<void> =>
    ipcRenderer.invoke(IPC_CHANNELS.BRIDGE_STOP),

  resetDecks: (): Promise<void> =>
    ipcRenderer.invoke(IPC_CHANNELS.BRIDGE_RESET_DECKS),

  reconnect: (): Promise<void> =>
    ipcRenderer.invoke(IPC_CHANNELS.BRIDGE_RECONNECT),

  restartBridge: (): Promise<void> =>
    ipcRenderer.invoke(IPC_CHANNELS.BRIDGE_RESTART),

  // Settings
  getSettings: (): Promise<BridgeSettings> =>
    ipcRenderer.invoke(IPC_CHANNELS.SETTINGS_GET),

  updateSettings: (settings: Partial<BridgeSettings>): Promise<BridgeSettings> =>
    ipcRenderer.invoke(IPC_CHANNELS.SETTINGS_UPDATE, settings),

  // Debug
  exportDebugReport: (): Promise<string | null> =>
    ipcRenderer.invoke(IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT),

  // Status subscriptions (main -> renderer)
  onBridgeStatus: (callback: (status: BridgeStatus) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, status: BridgeStatus) => callback(status);
    ipcRenderer.on(IPC_CHANNELS.BRIDGE_STATUS, listener);
    return () => ipcRenderer.removeListener(IPC_CHANNELS.BRIDGE_STATUS, listener);
  },

  onBridgeLog: (callback: (logMessage: IpcLogMessage) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, logMessage: IpcLogMessage) => callback(logMessage);
    ipcRenderer.on(IPC_CHANNELS.BRIDGE_LOG, listener);
    return () => ipcRenderer.removeListener(IPC_CHANNELS.BRIDGE_LOG, listener);
  },

  onPing: (callback: () => void): (() => void) => {
    const listener = () => callback();
    ipcRenderer.on(IPC_CHANNELS.BRIDGE_PING, listener);
    return () => ipcRenderer.removeListener(IPC_CHANNELS.BRIDGE_PING, listener);
  },

  onAuthChanged: (callback: (state: AuthState) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, state: AuthState) => callback(state);
    ipcRenderer.on(IPC_CHANNELS.AUTH_CHANGED, listener);
    return () => ipcRenderer.removeListener(IPC_CHANNELS.AUTH_CHANGED, listener);
  },
} satisfies BridgeApi;

contextBridge.exposeInMainWorld('bridgeApi', bridgeApi);
