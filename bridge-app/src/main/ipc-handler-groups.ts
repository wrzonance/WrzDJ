import { app, dialog, type BrowserWindow } from 'electron';
import { arch, platform, release } from 'node:os';
import { login, verifyToken, buildAuthState } from './auth-service.js';
import { fetchBridgeApiKey } from './bridge-api-key-service.js';
import { fetchEvents } from './events-service.js';
import { writeDebugReport } from './debug-report-service.js';
import { listPluginMeta } from '@wrzdj/bridge/electron';

import type { BridgeRunner } from './bridge-runner.js';
import type { LogFileWriter } from './log-file-writer.js';
import * as store from './store.js';
import { IPC_CHANNELS } from '../shared/types.js';
import type { BridgeSettings } from '../shared/types.js';
import type { IpcHandlerMap } from '../shared/ipc-contract.js';
import type { RendererEventMap } from '../shared/ipc-contract.js';

export type RegisterIpcHandler = <Channel extends keyof IpcHandlerMap>(
  channel: Channel,
  listener: IpcHandlerMap[Channel],
) => void;

interface HandlerContext {
  mainWindow: BrowserWindow;
  bridgeRunner: BridgeRunner;
  fileWriter: LogFileWriter;
  registerHandler: RegisterIpcHandler;
  sendToRenderer: <Channel extends keyof RendererEventMap>(channel: Channel, ...args: RendererEventMap[Channel]) => void;
}

type AccountHandlerContext = Pick<HandlerContext, 'bridgeRunner' | 'registerHandler' | 'sendToRenderer'>;
type BridgeHandlerContext = Pick<HandlerContext, 'bridgeRunner' | 'registerHandler'>;
type SettingsAndDiagnosticsContext = Pick<
  HandlerContext,
  'mainWindow' | 'bridgeRunner' | 'fileWriter' | 'registerHandler'
>;

let bridgeStartGeneration = 0;
let authSessionGeneration = 0;
let activeLogoutCount = 0;
let activeLoginCount = 0;

function invalidatePendingBridgeStart(): void {
  bridgeStartGeneration += 1;
}

function invalidateAuthSession(): number {
  authSessionGeneration += 1;
  invalidatePendingBridgeStart();
  return authSessionGeneration;
}

function assertBridgeStartStillCurrent(
  generation: number,
  authGeneration: number,
  apiUrl: string,
  token: string,
): void {
  if (
    generation !== bridgeStartGeneration ||
    authGeneration !== authSessionGeneration ||
    activeLogoutCount > 0 ||
    store.getApiUrl() !== apiUrl ||
    store.readAndRepairToken() !== token
  ) {
    throw new Error('Bridge start was cancelled because the session changed');
  }
}

/** Register authentication, plugin discovery, and event API handlers. */
export function registerAccountHandlers({ registerHandler, sendToRenderer, bridgeRunner }: AccountHandlerContext): void {
  registerHandler(IPC_CHANNELS.AUTH_LOGIN, async (_event, apiUrl: string, username: string, password: string) => {
    if (!isValidHttpUrl(apiUrl)) {
      throw new Error('Invalid API URL: must be a valid HTTP or HTTPS URL');
    }
    const loginGeneration = invalidateAuthSession();
    activeLoginCount += 1;
    try {
      const result = await login(apiUrl, username, password);
      if (loginGeneration !== authSessionGeneration) {
        throw new Error('Login was cancelled because the session changed');
      }
      store.setApiUrl(apiUrl);
      store.setToken(result.accessToken);
      sendToRenderer(IPC_CHANNELS.AUTH_CHANGED, buildAuthState(apiUrl, result.username));
    } finally {
      activeLoginCount -= 1;
    }
  });

  registerHandler(IPC_CHANNELS.AUTH_LOGOUT, async () => {
    activeLogoutCount += 1;
    invalidateAuthSession();
    try {
      try {
        // Revoke local auth at the intent boundary; stop() may await an older runtime shutdown.
        store.clearToken();
        sendToRenderer(IPC_CHANNELS.AUTH_CHANGED, buildAuthState(store.getApiUrl(), null));
      } finally {
        try {
          // stop() also invalidates a start waiting for an earlier runtime shutdown.
          await bridgeRunner.stop();
        } catch {
          // Ensure logout completes even if bridge stop fails.
        }
      }
    } finally {
      activeLogoutCount -= 1;
    }
  });

  registerHandler(IPC_CHANNELS.AUTH_GET_STATE, async () => {
    const verificationGeneration = authSessionGeneration;
    const apiUrl = store.getApiUrl();
    const token = store.readAndRepairToken();
    if (!token) return buildAuthState(apiUrl, null);

    try {
      const username = await verifyToken(apiUrl, token);
      if (
        verificationGeneration !== authSessionGeneration ||
        store.getApiUrl() !== apiUrl ||
        store.readAndRepairToken() !== token
      ) {
        return buildAuthState(store.getApiUrl(), null);
      }
      if (!username) {
        invalidateAuthSession();
        store.clearToken();
      }
      return buildAuthState(apiUrl, username);
    } catch {
      if (
        verificationGeneration !== authSessionGeneration ||
        store.getApiUrl() !== apiUrl ||
        store.readAndRepairToken() !== token
      ) {
        return buildAuthState(store.getApiUrl(), null);
      }
      return buildAuthState(
        apiUrl,
        null,
        'Could not verify the saved session. Check the connection and try again.',
      );
    }
  });

  registerHandler(IPC_CHANNELS.PLUGINS_LIST_META, () => listPluginMeta());
  registerHandler(IPC_CHANNELS.EVENTS_FETCH, async () => fetchEvents(store.getApiUrl(), requireStoredToken()));
}

/** Register bridge lifecycle and administrative controls. */
export function registerBridgeHandlers({ registerHandler, bridgeRunner }: BridgeHandlerContext): void {
  registerHandler(IPC_CHANNELS.BRIDGE_START, async (_event, eventCode: string) => {
    if (!isValidEventCode(eventCode)) {
      throw new Error('Invalid event code: must be 4-10 alphanumeric characters');
    }
    if (activeLogoutCount > 0) {
      throw new Error('Cannot start bridge while logout is in progress');
    }
    if (activeLoginCount > 0) {
      throw new Error('Cannot start bridge while login is in progress');
    }
    const apiUrl = store.getApiUrl();
    const token = requireStoredToken();
    const generation = ++bridgeStartGeneration;
    const authGeneration = authSessionGeneration;
    const apiKey = await fetchBridgeApiKey(apiUrl, token);
    assertBridgeStartStillCurrent(generation, authGeneration, apiUrl, token);
    store.setLastEventCode(eventCode);
    await bridgeRunner.start({ apiUrl, apiKey, eventCode, settings: store.getSettings() });
    assertBridgeStartStillCurrent(generation, authGeneration, apiUrl, token);
  });

  registerHandler(IPC_CHANNELS.BRIDGE_STOP, async () => {
    requireStoredToken();
    invalidatePendingBridgeStart();
    await bridgeRunner.stop();
  });
  registerHandler(IPC_CHANNELS.BRIDGE_RESET_DECKS, async () => {
    requireStoredToken();
    bridgeRunner.resetDecks();
  });
  registerHandler(IPC_CHANNELS.BRIDGE_RECONNECT, async () => {
    requireStoredToken();
    await bridgeRunner.reconnect();
  });
  registerHandler(IPC_CHANNELS.BRIDGE_RESTART, async () => {
    requireStoredToken();
    await bridgeRunner.restartBridge();
  });
}

/** Register settings and diagnostic export handlers. */
export function registerSettingsAndDiagnosticsHandlers({
  mainWindow,
  bridgeRunner,
  fileWriter,
  registerHandler,
}: SettingsAndDiagnosticsContext): void {
  registerHandler(IPC_CHANNELS.SETTINGS_GET, () => store.getSettings());
  registerHandler(IPC_CHANNELS.SETTINGS_UPDATE, (_event, partial: Partial<BridgeSettings>) => {
    return store.updateSettings(validateSettingsUpdate(partial));
  });

  registerHandler(IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT, async () => {
    const { filePath } = await dialog.showSaveDialog(mainWindow, {
      title: 'Export Debug Report',
      defaultPath: `wrzdj-debug-${new Date().toISOString().slice(0, 10)}.txt`,
      filters: [{ name: 'Text', extensions: ['txt'] }],
    });
    if (!filePath) return null;

    await writeDebugReport(filePath, {
      appVersion: app.getVersion(),
      electronVersion: process.versions.electron,
      nodeVersion: process.versions.node,
      chromeVersion: process.versions.chrome,
      os: `${platform()} ${release()} (${arch()})`,
      logPath: fileWriter.getLogPath(),
      status: bridgeRunner.getStatus(),
      settings: store.getSettings(),
    });
    return filePath;
  });
}

function isValidHttpUrl(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

function isValidEventCode(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Z0-9]{4,10}$/.test(value);
}

function requireStoredToken(): string {
  const token = store.readAndRepairToken();
  if (!token) throw new Error('Not authenticated');
  return token;
}

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

function validateSettingsUpdate(partial: unknown): Partial<BridgeSettings> {
  if (typeof partial !== 'object' || partial === null || Array.isArray(partial)) {
    throw new Error('Invalid settings: expected an object');
  }
  const validated: Record<string, unknown> = {};
  const nonNegativeNumberKeys = new Set([
    'liveThresholdSeconds', 'pauseGraceSeconds', 'nowPlayingPauseSeconds', 'minPlaySeconds',
  ]);
  for (const [key, value] of Object.entries(partial)) {
    const expectedType = SETTINGS_SCHEMA[key];
    if (!expectedType || typeof value !== expectedType) continue;
    if (key === 'pluginConfig' && (value === null || Array.isArray(value))) continue;
    if (expectedType === 'number') {
      const numericValue = value as number;
      if (!Number.isFinite(numericValue) || (nonNegativeNumberKeys.has(key) && numericValue < 0)) continue;
    }
    validated[key] = value;
  }
  return validated as Partial<BridgeSettings>;
}
