import { app, dialog, ipcMain, type BrowserWindow } from 'electron';
import { readFile, writeFile } from 'fs/promises';
import { platform, release, arch } from 'os';
import { login, verifyToken, buildAuthState } from './auth-service.js';
import { fetchBridgeApiKey } from './bridge-api-key-service.js';
import { fetchEvents } from './events-service.js';
import { LogFileWriter } from './log-file-writer.js';
import { listPluginMeta } from '@bridge/plugin-registry.js';
import { BridgeRunner } from './bridge-runner.js';
import * as store from './store.js';
import { IPC_CHANNELS } from '../shared/types.js';
import type { BridgeSettings, IpcLogMessage } from '../shared/types.js';

const bridgeRunner = new BridgeRunner();
const logFileWriter = new LogFileWriter(app.getPath('logs'));

/** Validate that a value is a valid HTTP(S) URL. */
function isValidHttpUrl(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

/** Validate that an event code matches the expected format. */
function isValidEventCode(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Z0-9]{4,10}$/.test(value);
}

/** Known BridgeSettings keys and their expected types. */
const SETTINGS_SCHEMA: Record<string, string> = {
  protocol: 'string',
  pluginConfig: 'object',
  liveThresholdSeconds: 'number',
  pauseGraceSeconds: 'number',
  nowPlayingPauseSeconds: 'number',
  useFaderDetection: 'boolean',
  masterDeckPriority: 'boolean',
  minPlaySeconds: 'number',
};

/** Validate and filter a settings update to only known keys with correct types. */
function validateSettingsUpdate(partial: unknown): Partial<BridgeSettings> {
  if (typeof partial !== 'object' || partial === null || Array.isArray(partial)) {
    throw new Error('Invalid settings: expected an object');
  }
  const validated: Record<string, unknown> = {};
  const nonNegativeNumberKeys = new Set([
    'liveThresholdSeconds',
    'pauseGraceSeconds',
    'nowPlayingPauseSeconds',
    'minPlaySeconds',
  ]);
  for (const [key, value] of Object.entries(partial)) {
    const expectedType = SETTINGS_SCHEMA[key];
    if (!expectedType) continue; // skip unknown keys
    if (typeof value !== expectedType) continue; // skip wrong types
    if (key === 'pluginConfig' && (value === null || Array.isArray(value))) continue;
    if (expectedType === 'number') {
      const numericValue = value as number;
      if (!Number.isFinite(numericValue)) continue;
      if (nonNegativeNumberKeys.has(key) && numericValue < 0) continue;
    }
    validated[key] = value;
  }
  return validated as Partial<BridgeSettings>;
}

export function registerIpcHandlers(mainWindow: BrowserWindow): void {
  const registeredChannels: string[] = [];
  const registerHandler = (channel: string, listener: (...args: any[]) => any): void => {
    ipcMain.handle(channel, listener);
    registeredChannels.push(channel);
  };
  const sendToRenderer = (channel: string, ...args: unknown[]): void => {
    if (!mainWindow.isDestroyed()) {
      mainWindow.webContents.send(channel, ...args);
    }
  };
  const statusChanged = (status: unknown) => sendToRenderer(IPC_CHANNELS.BRIDGE_STATUS, status);
  const ping = () => sendToRenderer(IPC_CHANNELS.BRIDGE_PING);
  const log = (logMessage: IpcLogMessage) => {
    logFileWriter.write(logMessage.level, logMessage.message);
    sendToRenderer(IPC_CHANNELS.BRIDGE_LOG, logMessage);
  };
  bridgeRunner.on('statusChanged', statusChanged);
  bridgeRunner.on('ping', ping);
  bridgeRunner.on('log', log);
  const cleanup = () => {
    for (const channel of registeredChannels) ipcMain.removeHandler(channel);
    bridgeRunner.off('statusChanged', statusChanged);
    bridgeRunner.off('ping', ping);
    bridgeRunner.off('log', log);
  };
  mainWindow.once('closed', cleanup);
  // --- Auth ---

  registerHandler(IPC_CHANNELS.AUTH_LOGIN, async (_event, apiUrl: string, username: string, password: string) => {
    if (!isValidHttpUrl(apiUrl)) {
      throw new Error('Invalid API URL: must be a valid HTTP or HTTPS URL');
    }
    const result = await login(apiUrl, username, password);
    store.setApiUrl(apiUrl);
    store.setToken(result.accessToken);

    const authState = buildAuthState(apiUrl, result.username);
    sendToRenderer(IPC_CHANNELS.AUTH_CHANGED, authState);
  });

  registerHandler(IPC_CHANNELS.AUTH_LOGOUT, async () => {
    if (bridgeRunner.isRunning) {
      try {
        await bridgeRunner.stop();
      } catch {
        // Ensure logout completes even if bridge stop fails
      }
    }
    store.clearToken();

    const authState = buildAuthState(store.getApiUrl(), null);
    sendToRenderer(IPC_CHANNELS.AUTH_CHANGED, authState);
  });

  registerHandler(IPC_CHANNELS.AUTH_GET_STATE, async () => {
    const apiUrl = store.getApiUrl();
    const token = store.getToken();

    if (!token) {
      return buildAuthState(apiUrl, null);
    }

    try {
      const username = await verifyToken(apiUrl, token);
      if (!username) store.clearToken();
      return buildAuthState(apiUrl, username);
    } catch {
      return buildAuthState(apiUrl, null);
    }
  });

  // --- Plugins ---

  registerHandler(IPC_CHANNELS.PLUGINS_LIST_META, () => {
    return listPluginMeta();
  });

  // --- Events ---

  registerHandler(IPC_CHANNELS.EVENTS_FETCH, async () => {
    const apiUrl = store.getApiUrl();
    const token = store.getToken();

    if (!token) {
      throw new Error('Not authenticated');
    }

    return fetchEvents(apiUrl, token);
  });

  // --- Bridge ---

  registerHandler(IPC_CHANNELS.BRIDGE_START, async (_event, eventCode: string) => {
    if (!isValidEventCode(eventCode)) {
      throw new Error('Invalid event code: must be 4-10 alphanumeric characters');
    }
    store.setLastEventCode(eventCode);

    const apiUrl = store.getApiUrl();
    const token = store.getToken();

    if (!token) {
      throw new Error('Not authenticated');
    }

    const apiKey = await fetchBridgeApiKey(apiUrl, token);
    const settings = store.getSettings();

    await bridgeRunner.start({
      apiUrl,
      apiKey,
      eventCode,
      settings,
    });
  });

  registerHandler(IPC_CHANNELS.BRIDGE_STOP, async () => {
    await bridgeRunner.stop();
  });

  // --- Bridge admin commands ---

  registerHandler(IPC_CHANNELS.BRIDGE_RESET_DECKS, async () => {
    await bridgeRunner.resetDecks();
  });

  registerHandler(IPC_CHANNELS.BRIDGE_RECONNECT, async () => {
    await bridgeRunner.reconnect();
  });

  registerHandler(IPC_CHANNELS.BRIDGE_RESTART, async () => {
    await bridgeRunner.restartBridge();
  });

  // --- Settings ---

  registerHandler(IPC_CHANNELS.SETTINGS_GET, () => {
    return store.getSettings();
  });

  registerHandler(IPC_CHANNELS.SETTINGS_UPDATE, (_event, partial: Partial<BridgeSettings>) => {
    const validated = validateSettingsUpdate(partial);
    return store.updateSettings(validated);
  });

  // --- Debug Report ---

  registerHandler(IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT, async () => {
    const { filePath } = await dialog.showSaveDialog(mainWindow, {
      title: 'Export Debug Report',
      defaultPath: `wrzdj-debug-${new Date().toISOString().slice(0, 10)}.txt`,
      filters: [{ name: 'Text', extensions: ['txt'] }],
    });

    if (!filePath) return null;

    const status = bridgeRunner.getStatus();
    const settings = store.getSettings();

    const logContents = await (async () => {
      const paths = [logFileWriter.getLogPath(), `${logFileWriter.getLogPath()}.1`];
      try {
        return await readFile(paths[0], 'utf-8');
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') return '(no log file found)';
      }
      try {
        return await readFile(paths[1], 'utf-8');
      } catch {
        return '(no log file found)';
      }
    })();

    const lines = [
      '=== WrzDJ Bridge Debug Report ===',
      `Generated: ${new Date().toISOString()}`,
      '',
      '--- System ---',
      `App Version: ${app.getVersion()}`,
      `Electron: ${process.versions.electron}`,
      `Node: ${process.versions.node}`,
      `Chrome: ${process.versions.chrome}`,
      `OS: ${platform()} ${release()} (${arch()})`,
      '',
      '--- Bridge Status ---',
      `Running: ${status.isRunning}`,
      `Event Code: ${status.eventCode ?? 'none'}`,
      `Connected Device: ${status.connectedDevice ?? 'none'}`,
      `Backend Reachable: ${status.backendReachable}`,
      `Stop Reason: ${status.stopReason ?? 'none'}`,
      `Current Track: ${status.currentTrack ? `"${status.currentTrack.title}" by ${status.currentTrack.artist}` : 'none'}`,
      `Active Decks: ${status.deckStates.length}`,
      `Network Warnings: ${status.networkWarnings.length > 0 ? status.networkWarnings.join('; ') : 'none'}`,
      '',
      '--- Settings ---',
      `Protocol: ${settings.protocol}`,
      `Live Threshold: ${settings.liveThresholdSeconds}s`,
      `Pause Grace: ${settings.pauseGraceSeconds}s`,
      `Now Playing Pause: ${settings.nowPlayingPauseSeconds}s`,
      `Fader Detection: ${settings.useFaderDetection}`,
      `Master Deck Priority: ${settings.masterDeckPriority}`,
      `Min Play Seconds: ${settings.minPlaySeconds}`,
      ...(settings.pluginConfig ? [`Plugin Config: ${JSON.stringify(settings.pluginConfig)}`] : []),
      '',
      '--- Log File ---',
      logContents,
    ];

    await writeFile(filePath, lines.join('\n'), 'utf-8');
    return filePath;
  });
}

/**
 * Get the bridge runner instance (for cleanup on app quit).
 */
export function getBridgeRunner(): BridgeRunner {
  return bridgeRunner;
}

/**
 * Get the path to the bridge log file (for debug report export).
 */
export function getLogFilePath(): string {
  return logFileWriter.getLogPath();
}
