import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const appListeners = new Map<string, (...args: unknown[]) => unknown>();
  const webRequest = { onHeadersReceived: vi.fn() };
  const mainWindow = {
    once: vi.fn(),
    loadURL: vi.fn(),
    loadFile: vi.fn(),
  };
  return {
    appListeners,
    app: {
      whenReady: vi.fn(() => Promise.resolve()),
      on: vi.fn((event: string, listener: (...args: unknown[]) => unknown) => appListeners.set(event, listener)),
      quit: vi.fn(),
      exit: vi.fn(),
      getPath: vi.fn(() => '/tmp/logs'),
      getVersion: vi.fn(() => '1.0.0'),
    },
    session: { defaultSession: { webRequest } },
    mainWindow,
    browserWindows: [] as unknown[],
    BrowserWindow: vi.fn(function MockBrowserWindow() {
      mocks.browserWindows.push(mainWindow);
      return mainWindow;
    }),
    registerIpcHandlers: vi.fn(),
    registerBuiltinPlugins: vi.fn(),
    runner: { isRunning: true, stop: vi.fn(async () => {}) },
  };
});

vi.mock('electron-squirrel-startup', () => ({ default: false }));
vi.mock('electron', () => ({
  app: mocks.app,
  BrowserWindow: Object.assign(mocks.BrowserWindow, { getAllWindows: () => [] }),
  session: mocks.session,
}));
vi.mock('../ipc-handlers.js', () => ({
  registerIpcHandlers: mocks.registerIpcHandlers,
  getBridgeRunner: () => mocks.runner,
}));
vi.mock('@wrzdj/bridge/electron', () => ({
  registerBuiltinPlugins: mocks.registerBuiltinPlugins,
}));

function stubPlatform(platform: NodeJS.Platform): void {
  const processMock = Object.create(process) as NodeJS.Process;
  Object.defineProperty(processMock, 'platform', { value: platform });
  Object.defineProperty(processMock, 'on', { value: process.on.bind(process) });
  Object.defineProperty(processMock, 'listeners', { value: process.listeners.bind(process) });
  vi.stubGlobal('process', processMock);
}

describe('Electron main lifecycle', () => {
  afterEach(() => vi.unstubAllGlobals());

  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal('MAIN_WINDOW_VITE_DEV_SERVER_URL', 'http://localhost:3000');
    vi.stubGlobal('MAIN_WINDOW_VITE_NAME', 'main_window');
    mocks.appListeners.clear();
    mocks.browserWindows.length = 0;
    vi.clearAllMocks();
    mocks.runner.isRunning = true;
    mocks.runner.stop.mockResolvedValue(undefined);
  });

  it('configures the first window on ready and recreates a window on activate', async () => {
    await import('../main.js');
    await Promise.resolve();
    expect(mocks.browserWindows).toHaveLength(1);
    expect(mocks.registerIpcHandlers).toHaveBeenCalledOnce();
    // Regression for import-order-dependent registration in baseline 57cfcdc6867f.
    expect(mocks.registerBuiltinPlugins).toHaveBeenCalledOnce();
    expect(mocks.registerBuiltinPlugins.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.registerIpcHandlers.mock.invocationCallOrder[0],
    );

    mocks.appListeners.get('activate')?.();
    expect(mocks.browserWindows).toHaveLength(2);
    expect(mocks.registerIpcHandlers).toHaveBeenCalledTimes(2);
  });

  it('stops the bridge when all windows close', async () => {
    await import('../main.js');
    await Promise.resolve();
    await mocks.appListeners.get('window-all-closed')?.();
    expect(mocks.runner.stop).toHaveBeenCalledOnce();
  });

  it('quits on non-macOS when bridge cleanup rejects', async () => {
    stubPlatform('linux');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mocks.runner.stop.mockRejectedValueOnce(new Error('sensitive device detail'));
    await import('../main.js');
    await Promise.resolve();

    await expect(mocks.appListeners.get('window-all-closed')?.()).resolves.toBeUndefined();

    expect(mocks.app.quit).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith('[Lifecycle] Bridge cleanup failed; continuing application shutdown');
    expect(warn.mock.calls.flat().join(' ')).not.toContain('sensitive device detail');
  });

  it('keeps the macOS app open when bridge cleanup rejects after the last window closes', async () => {
    stubPlatform('darwin');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mocks.runner.stop.mockRejectedValueOnce(new Error('cleanup failed'));
    await import('../main.js');
    await Promise.resolve();

    await expect(mocks.appListeners.get('window-all-closed')?.()).resolves.toBeUndefined();

    expect(mocks.app.quit).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledOnce();
  });

  it('keeps the macOS app open after successful bridge cleanup', async () => {
    stubPlatform('darwin');
    await import('../main.js');
    await Promise.resolve();

    await mocks.appListeners.get('window-all-closed')?.();

    expect(mocks.runner.stop).toHaveBeenCalledOnce();
    expect(mocks.app.quit).not.toHaveBeenCalled();
  });

  it('waits for an in-progress bridge stop before quitting on a second window-close event', async () => {
    let completeStop: (() => void) | undefined;
    let stopPromise: Promise<void> | undefined;
    mocks.runner.stop.mockImplementation(() => {
      if (!stopPromise) {
        mocks.runner.isRunning = false;
        stopPromise = new Promise<void>((resolve) => {
          completeStop = resolve;
        });
      }
      return stopPromise;
    });

    const stopInProgress = mocks.runner.stop();
    await import('../main.js');
    await Promise.resolve();
    const closeAllWindows = mocks.appListeners.get('window-all-closed');
    const close = closeAllWindows?.();

    expect(mocks.app.quit).not.toHaveBeenCalled();
    completeStop?.();
    await Promise.all([stopInProgress, close]);
    expect(mocks.app.quit).toHaveBeenCalledOnce();
  });

  it('does not write rejected background-operation content into logs', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    await import('../main.js');
    const rejectionHandler = process.listeners('unhandledRejection').at(-1);

    rejectionHandler?.(new Error('credential=do-not-log'), Promise.resolve());

    expect(warn).toHaveBeenCalledOnce();
    expect(warn.mock.calls.flat().join(' ')).not.toContain('do-not-log');
    warn.mockRestore();
  });
});
