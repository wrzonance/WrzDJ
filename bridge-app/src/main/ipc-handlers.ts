import { app, ipcMain, type BrowserWindow } from 'electron';
import { LogFileWriter } from './log-file-writer.js';
import { BridgeRunner } from './bridge-runner.js';
import { IPC_CHANNELS } from '../shared/types.js';
import type { BridgeStatus, IpcLogMessage } from '../shared/types.js';
import type { IpcHandlerMap, RendererEventMap } from '../shared/ipc-contract.js';
import {
  registerAccountHandlers,
  registerBridgeHandlers,
  registerSettingsAndDiagnosticsHandlers,
} from './ipc-handler-groups.js';
import * as store from './store.js';

const bridgeRunner = new BridgeRunner();
let logFileWriter: LogFileWriter | null = null;

/** Set up renderer event forwarding, handler registration, and window cleanup. */
export function registerIpcHandlers(mainWindow: BrowserWindow): void {
  store.initializeStore();
  logFileWriter ??= new LogFileWriter(app.getPath('logs'));
  const fileWriter = logFileWriter;
  const registeredChannels: string[] = [];
  const registerHandler = <Channel extends keyof IpcHandlerMap>(
    channel: Channel,
    listener: IpcHandlerMap[Channel],
  ): void => {
    ipcMain.handle(channel, listener);
    registeredChannels.push(channel);
  };
  const sendToRenderer = <Channel extends keyof RendererEventMap>(
    channel: Channel,
    ...args: RendererEventMap[Channel]
  ): void => {
    if (!mainWindow.isDestroyed()) mainWindow.webContents.send(channel, ...args);
  };
  const statusChanged = (status: BridgeStatus) => sendToRenderer(IPC_CHANNELS.BRIDGE_STATUS, status);
  const ping = () => sendToRenderer(IPC_CHANNELS.BRIDGE_PING);
  const log = (logMessage: IpcLogMessage) => {
    fileWriter.write(logMessage.level, logMessage.message);
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

  const context = { mainWindow, bridgeRunner, fileWriter, registerHandler, sendToRenderer };
  registerAccountHandlers(context);
  registerBridgeHandlers(context);
  registerSettingsAndDiagnosticsHandlers(context);
}

/** Get the bridge runner instance (for cleanup on app quit). */
export function getBridgeRunner(): BridgeRunner {
  return bridgeRunner;
}

/** Get the path to the bridge log file (for debug report export). */
export function getLogFilePath(): string {
  if (!logFileWriter) throw new Error('Log file writer has not been initialized');
  return logFileWriter.getLogPath();
}
