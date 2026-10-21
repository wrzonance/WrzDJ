import started from 'electron-squirrel-startup';
if (started) process.exit();

import { app, BrowserWindow, session } from 'electron';

// Squirrel auto-launches the app with --squirrel-firstrun after install completes.
// Exit immediately so the installer process tree terminates cleanly.
// Without this, winget validation times out waiting for the app to close (E_ABORT).
if (process.argv.includes('--squirrel-firstrun')) {
  app.exit(0);
}
import path from 'path';
import { registerBuiltinPlugins } from '@wrzdj/bridge/electron';
import { registerIpcHandlers, getBridgeRunner } from './ipc-handlers.js';

// Catch unhandled rejections from third-party libraries (e.g. stagelinq retry failures)
// so they log a warning instead of crashing the process.
process.on('unhandledRejection', () => {
  console.warn('[UnhandledRejection] Background operation failed');
});

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string | undefined;
declare const MAIN_WINDOW_VITE_NAME: string;

function createWindow(): BrowserWindow {
  const mainWindow = new BrowserWindow({
    width: 900,
    height: 680,
    minWidth: 700,
    minHeight: 500,
    title: 'WrzDJ Bridge',
    backgroundColor: '#0a0a0a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Register IPC handlers with this window
  registerIpcHandlers(mainWindow);

  // Load the renderer
  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(
      path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`),
    );
  }

  return mainWindow;
}

app.whenReady().then(() => {
  registerBuiltinPlugins();
  // Set Content Security Policy for all renderer pages
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'",
        ],
      },
    });
  });

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', async () => {
  try {
    // stop() also returns an in-progress shutdown, even after isRunning is cleared.
    await getBridgeRunner().stop();
  } catch {
    // Shutdown must still finish; BridgeRunner records the cleanup failure safely.
    console.warn('[Lifecycle] Bridge cleanup failed; continuing application shutdown');
  } finally {
    if (process.platform !== 'darwin') {
      app.quit();
    }
  }
});
