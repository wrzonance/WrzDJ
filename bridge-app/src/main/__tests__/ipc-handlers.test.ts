import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EventEmitter } from 'events';
import { IPC_CHANNELS, DEFAULT_SETTINGS } from '../../shared/types.js';

const mocks = vi.hoisted(() => {
  const handlers = new Map<string, (...args: unknown[]) => unknown>();
  const store = {
    initializeStore: vi.fn(),
    getApiUrl: vi.fn(() => 'https://api.example.test'),
    readAndRepairToken: vi.fn(() => 'stored-token'),
    setApiUrl: vi.fn(),
    setToken: vi.fn(),
    clearToken: vi.fn(),
    setLastEventCode: vi.fn(),
    getLastEventCode: vi.fn(() => null),
    getSettings: vi.fn(() => DEFAULT_SETTINGS),
    updateSettings: vi.fn((settings) => ({ ...DEFAULT_SETTINGS, ...settings })),
  };
  class MockBridgeRunner {
    private listeners = new Map<string, (...args: unknown[]) => void>();
    isRunning = false;
    on = vi.fn((event: string, listener: (...args: unknown[]) => void) => {
      this.listeners.set(event, listener);
      return this;
    });
    off = vi.fn((event: string, listener: (...args: unknown[]) => void) => {
      if (this.listeners.get(event) === listener) this.listeners.delete(event);
      return this;
    });
    emit = (event: string, ...args: unknown[]) => this.listeners.get(event)?.(...args);
    start = vi.fn();
    stop = vi.fn();
    resetDecks = vi.fn();
    reconnect = vi.fn();
    restartBridge = vi.fn();
    getStatus = vi.fn(() => ({
      isRunning: false,
      eventCode: null,
      connectedDevice: null,
      backendReachable: false,
      stopReason: null,
      currentTrack: null,
      deckStates: [],
      networkWarnings: [],
    }));
  }
  class MockLogFileWriter {
    write = vi.fn();
    getLogPath = vi.fn(() => '/tmp/wrzdj.log');
  }
  return {
    handlers,
    store,
    MockBridgeRunner,
    MockLogFileWriter,
    dialog: { showSaveDialog: vi.fn() },
    readFile: vi.fn(),
    writeFile: vi.fn(),
    mkdtemp: vi.fn(),
    rename: vi.fn(),
    rm: vi.fn(),
    verifyToken: vi.fn(),
    login: vi.fn(),
    fetchBridgeApiKey: vi.fn(),
    fetchEvents: vi.fn(),
  };
});

vi.mock('electron', () => ({
  app: { getPath: vi.fn(() => '/tmp'), getVersion: vi.fn(() => 'test') },
  dialog: mocks.dialog,
  ipcMain: {
    handle: vi.fn((channel, handler) => {
      if (mocks.handlers.has(channel)) throw new Error(`Duplicate IPC handler: ${channel}`);
      mocks.handlers.set(channel, handler);
    }),
    removeHandler: vi.fn((channel) => mocks.handlers.delete(channel)),
  },
}));
vi.mock('fs/promises', () => ({
  default: {
    readFile: mocks.readFile,
    writeFile: mocks.writeFile,
    mkdtemp: mocks.mkdtemp,
    rename: mocks.rename,
    rm: mocks.rm,
  },
  readFile: mocks.readFile,
  writeFile: mocks.writeFile,
  mkdtemp: mocks.mkdtemp,
  rename: mocks.rename,
  rm: mocks.rm,
}));
vi.mock('../store.js', () => mocks.store);
vi.mock('../auth-service.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../auth-service.js')>()),
  verifyToken: mocks.verifyToken,
  login: mocks.login,
}));
vi.mock('../bridge-runner.js', () => ({ BridgeRunner: mocks.MockBridgeRunner }));
vi.mock('../log-file-writer.js', () => ({ LogFileWriter: mocks.MockLogFileWriter }));
vi.mock('../bridge-api-key-service.js', () => ({ fetchBridgeApiKey: mocks.fetchBridgeApiKey }));
vi.mock('../events-service.js', () => ({ fetchEvents: mocks.fetchEvents }));
vi.mock('@wrzdj/bridge/electron', () => ({ listPluginMeta: vi.fn(() => []), registerBuiltinPlugins: vi.fn() }));

const { registerIpcHandlers, getBridgeRunner, getLogFilePath } = await import('../ipc-handlers.js');

type TestWindow = EventEmitter & {
  isDestroyed: ReturnType<typeof vi.fn>;
  webContents: { send: ReturnType<typeof vi.fn> };
};

const mainWindow = Object.assign(new EventEmitter(), {
  isDestroyed: vi.fn(() => false),
  webContents: { send: vi.fn() },
}) as TestWindow;

function handler(channel: string): (...args: unknown[]) => unknown {
  const registered = mocks.handlers.get(channel);
  if (!registered) throw new Error(`Missing IPC handler: ${channel}`);
  return registered;
}

beforeEach(() => {
  mainWindow.emit('closed');
  mocks.handlers.clear();
  vi.clearAllMocks();
  mainWindow.isDestroyed.mockReturnValue(false);
  mocks.store.getApiUrl.mockReturnValue('https://api.example.test');
  mocks.store.readAndRepairToken.mockReturnValue('stored-token');
  mocks.store.getApiUrl.mockReturnValue('https://api.example.test');
  mocks.store.getSettings.mockReturnValue(DEFAULT_SETTINGS);
  (getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>).isRunning = false;
  mocks.login.mockResolvedValue({ accessToken: 'new-token', username: 'dj' });
  mocks.fetchBridgeApiKey.mockResolvedValue('bridge-key');
  mocks.dialog.showSaveDialog.mockResolvedValue({ filePath: '/tmp/report.txt' });
  mocks.readFile.mockResolvedValue('bridge log');
  mocks.writeFile.mockResolvedValue(undefined);
  mocks.mkdtemp.mockResolvedValue('/tmp/.wrzdj-debug-report-unique');
  mocks.rename.mockResolvedValue(undefined);
  mocks.rm.mockResolvedValue(undefined);
  registerIpcHandlers(mainWindow as never);
});

describe('settings:update IPC boundary', () => {
  it('returns current settings through settings:get', () => {
    expect(handler(IPC_CHANNELS.SETTINGS_GET)({})).toEqual(DEFAULT_SETTINGS);
  });

  it('filters non-finite and negative timings while accepting zero and plain config objects', async () => {
    // Regression coverage for 99f9a2b: reject invalid timing values at the IPC boundary.
    await handler(IPC_CHANNELS.SETTINGS_UPDATE)({}, {
      liveThresholdSeconds: Number.NaN,
      pauseGraceSeconds: Number.POSITIVE_INFINITY,
      nowPlayingPauseSeconds: -1,
      minPlaySeconds: 0,
      pluginConfig: { device: 'alpha' },
    });

    expect(mocks.store.updateSettings).toHaveBeenCalledWith({
      minPlaySeconds: 0,
      pluginConfig: { device: 'alpha' },
    });
  });

  it('rejects null and array plugin configurations', async () => {
    const update = handler(IPC_CHANNELS.SETTINGS_UPDATE);

    await update({}, { pluginConfig: null });
    expect(mocks.store.updateSettings).toHaveBeenLastCalledWith({});

    await update({}, { pluginConfig: [] });

    expect(mocks.store.updateSettings).toHaveBeenLastCalledWith({});
    expect(mocks.store.updateSettings).toHaveBeenCalledTimes(2);
  });
});

describe('auth:login IPC boundary', () => {
  it('rejects non-HTTP API URLs before calling the login service', async () => {
    await expect(handler(IPC_CHANNELS.AUTH_LOGIN)({}, 'file:///tmp/api', 'dj', 'secret'))
      .rejects.toThrow('valid HTTP or HTTPS URL');
  });

  it('stores successful credentials without sending to a closed window', async () => {
    let resolveLogin!: (result: { accessToken: string; username: string }) => void;
    mocks.login.mockImplementationOnce(() => new Promise((resolve) => { resolveLogin = resolve; }));
    const loginRequest = handler(IPC_CHANNELS.AUTH_LOGIN)({}, 'https://custom.example', 'dj', 'secret');
    mainWindow.isDestroyed.mockReturnValue(true);
    mainWindow.emit('closed');
    resolveLogin({ accessToken: 'new-token', username: 'dj' });

    await expect(loginRequest).resolves.toBeUndefined();
    expect(mocks.store.setApiUrl).toHaveBeenCalledWith('https://custom.example');
    expect(mocks.store.setToken).toHaveBeenCalledWith('new-token');
    expect(mainWindow.webContents.send).not.toHaveBeenCalled();
  });
});

describe('auth:logout IPC boundary', () => {
  it('clears the stored token and notifies the renderer', async () => {
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    await handler(IPC_CHANNELS.AUTH_LOGOUT)({});

    expect(runner.stop).toHaveBeenCalledOnce();
    expect(mocks.store.clearToken).toHaveBeenCalledOnce();
    expect(mainWindow.webContents.send).toHaveBeenCalledWith(
      IPC_CHANNELS.AUTH_CHANGED,
      expect.objectContaining({ isAuthenticated: false }),
    );
  });

  it('does not send another logout event after the window closes during stop', async () => {
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    runner.isRunning = true;
    let resolveStop!: () => void;
    runner.stop.mockImplementationOnce(() => new Promise<void>((resolve) => { resolveStop = resolve; }));
    const logoutRequest = handler(IPC_CHANNELS.AUTH_LOGOUT)({});
    expect(mainWindow.webContents.send).toHaveBeenCalledOnce();
    mainWindow.isDestroyed.mockReturnValue(true);
    mainWindow.emit('closed');
    resolveStop();

    await expect(logoutRequest).resolves.toBeUndefined();
    expect(mocks.store.clearToken).toHaveBeenCalledOnce();
    expect(mainWindow.webContents.send).toHaveBeenCalledOnce();
  });

  it('still clears credentials when best-effort bridge shutdown fails', async () => {
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    runner.isRunning = true;
    runner.stop.mockRejectedValueOnce(new Error('device cleanup failed'));

    await expect(handler(IPC_CHANNELS.AUTH_LOGOUT)({})).resolves.toBeUndefined();

    expect(mocks.store.clearToken).toHaveBeenCalledOnce();
  });

  it('keeps a successful newer login when an older logout stop finishes later', async () => {
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    let resolveStop!: () => void;
    runner.stop.mockImplementationOnce(() => new Promise<void>((resolve) => { resolveStop = resolve; }));

    const logoutRequest = handler(IPC_CHANNELS.AUTH_LOGOUT)({});
    let sendsBeforeOldStopFinishes: number;
    try {
      expect(mocks.store.clearToken).toHaveBeenCalledOnce();
      expect(mainWindow.webContents.send).toHaveBeenLastCalledWith(
        IPC_CHANNELS.AUTH_CHANGED,
        expect.objectContaining({ isAuthenticated: false }),
      );

      await handler(IPC_CHANNELS.AUTH_LOGIN)({}, 'https://new.example', 'new-dj', 'password');
      sendsBeforeOldStopFinishes = mainWindow.webContents.send.mock.calls.length;
      expect(mocks.store.setToken).toHaveBeenCalledWith('new-token');
      expect(mainWindow.webContents.send).toHaveBeenLastCalledWith(
        IPC_CHANNELS.AUTH_CHANGED,
        expect.objectContaining({ isAuthenticated: true, username: 'dj' }),
      );
    } finally {
      resolveStop();
      await logoutRequest;
    }

    expect(mocks.store.clearToken).toHaveBeenCalledOnce();
    expect(mainWindow.webContents.send).toHaveBeenCalledTimes(sendsBeforeOldStopFinishes);
    expect(mainWindow.webContents.send).toHaveBeenLastCalledWith(
      IPC_CHANNELS.AUTH_CHANGED,
      expect.objectContaining({ isAuthenticated: true, username: 'dj' }),
    );
  });

  it('leaves logout effective when a newer login attempt fails during bridge shutdown', async () => {
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    let resolveStop!: () => void;
    runner.stop.mockImplementationOnce(() => new Promise<void>((resolve) => { resolveStop = resolve; }));
    mocks.login.mockRejectedValueOnce(new Error('invalid credentials'));

    const logoutRequest = handler(IPC_CHANNELS.AUTH_LOGOUT)({});
    let sendsBeforeOldStopFinishes: number;
    try {
      const failedLogin = handler(IPC_CHANNELS.AUTH_LOGIN)({}, 'https://new.example', 'new-dj', 'wrong');
      await expect(failedLogin).rejects.toThrow('invalid credentials');
      expect(mocks.store.clearToken).toHaveBeenCalledOnce();
      expect(mainWindow.webContents.send).toHaveBeenLastCalledWith(
        IPC_CHANNELS.AUTH_CHANGED,
        expect.objectContaining({ isAuthenticated: false }),
      );
      sendsBeforeOldStopFinishes = mainWindow.webContents.send.mock.calls.length;
    } finally {
      resolveStop();
      await logoutRequest;
    }

    expect(mocks.store.clearToken).toHaveBeenCalledOnce();
    expect(mocks.store.setToken).not.toHaveBeenCalled();
    expect(mainWindow.webContents.send).toHaveBeenCalledTimes(sendsBeforeOldStopFinishes);
  });

  it('does not restore credentials when logout supersedes a pending login', async () => {
    let resolveLogin!: (result: { accessToken: string; username: string }) => void;
    mocks.login.mockImplementationOnce(() => new Promise((resolve) => {
      resolveLogin = resolve;
    }));

    const loginRequest = handler(IPC_CHANNELS.AUTH_LOGIN)({}, 'https://other.example', 'dj', 'secret');
    await handler(IPC_CHANNELS.AUTH_LOGOUT)({});
    resolveLogin({ accessToken: 'new-token', username: 'dj' });

    await expect(loginRequest).rejects.toThrow('session changed');
    expect(mocks.store.clearToken).toHaveBeenCalledOnce();
    expect(mocks.store.setToken).not.toHaveBeenCalled();
    expect(mocks.store.setApiUrl).not.toHaveBeenCalled();
  });
});

describe('events:fetch IPC boundary', () => {
  it('rejects unauthenticated event fetches', async () => {
    mocks.store.readAndRepairToken.mockReturnValue(null as unknown as string);

    await expect(handler(IPC_CHANNELS.EVENTS_FETCH)({})).rejects.toThrow('Not authenticated');
  });
});

describe('bridge control IPC boundary', () => {
  it.each([
    [IPC_CHANNELS.BRIDGE_STOP, 'stop'],
    [IPC_CHANNELS.BRIDGE_RESET_DECKS, 'resetDecks'],
    [IPC_CHANNELS.BRIDGE_RECONNECT, 'reconnect'],
    [IPC_CHANNELS.BRIDGE_RESTART, 'restartBridge'],
  ] as const)('rejects unauthenticated %s requests before calling the runner', async (channel, method) => {
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    mocks.store.readAndRepairToken.mockReturnValue(null as unknown as string);

    await expect(handler(channel)({})).rejects.toThrow('Not authenticated');
    expect(runner[method]).not.toHaveBeenCalled();
  });
});

describe('auth:getState IPC boundary', () => {
  it('returns the configured URL and retains a token when verification is unavailable', async () => {
    mocks.store.getApiUrl.mockReturnValue('https://custom.example');
    mocks.verifyToken.mockRejectedValueOnce(new Error('offline'));

    await expect(handler(IPC_CHANNELS.AUTH_GET_STATE)({})).resolves.toEqual({
      isAuthenticated: false,
      username: null,
      apiUrl: 'https://custom.example',
      verificationError: 'Could not verify the saved session. Check the connection and try again.',
    });
    expect(mocks.store.clearToken).not.toHaveBeenCalled();
  });

  it('returns the configured URL without verifying when no token is stored', async () => {
    mocks.store.getApiUrl.mockReturnValue('https://custom.example');
    mocks.store.readAndRepairToken.mockReturnValueOnce(null as unknown as string);

    await expect(handler(IPC_CHANNELS.AUTH_GET_STATE)({})).resolves.toEqual({
      isAuthenticated: false,
      username: null,
      apiUrl: 'https://custom.example',
      verificationError: null,
    });
    expect(mocks.verifyToken).not.toHaveBeenCalled();
  });

  it('clears an invalid stored token', async () => {
    mocks.verifyToken.mockResolvedValueOnce(null);

    const state = await handler(IPC_CHANNELS.AUTH_GET_STATE)({});

    expect(mocks.store.clearToken).toHaveBeenCalledOnce();
    expect(state).toEqual({
      isAuthenticated: false,
      username: null,
      apiUrl: 'https://api.example.test',
      verificationError: null,
    });
  });

  it('restores a valid stored token', async () => {
    mocks.verifyToken.mockResolvedValueOnce('dj-admin');

    const state = await handler(IPC_CHANNELS.AUTH_GET_STATE)({});

    expect(mocks.store.clearToken).not.toHaveBeenCalled();
    expect(state).toEqual({
      isAuthenticated: true,
      username: 'dj-admin',
      apiUrl: 'https://api.example.test',
      verificationError: null,
    });
  });

  it('does not clear a newer login when saved-token verification completes stale', async () => {
    // Regression for 57cfcdc6867f: a delayed rejection for token A must not clear token B.
    let finishVerification!: (username: string | null) => void;
    mocks.verifyToken.mockImplementationOnce(() => new Promise((resolve) => {
      finishVerification = resolve;
    }));
    mocks.store.setApiUrl.mockImplementation((url: string) => {
      mocks.store.getApiUrl.mockReturnValue(url);
    });
    const staleVerification = handler(IPC_CHANNELS.AUTH_GET_STATE)({}) as Promise<unknown>;

    await handler(IPC_CHANNELS.AUTH_LOGIN)({}, 'https://new.example', 'new-dj', 'password');
    finishVerification(null);
    await staleVerification;

    expect(mocks.store.setApiUrl).toHaveBeenCalledWith('https://new.example');
    expect(mocks.store.setToken).toHaveBeenCalledWith('new-token');
    expect(mocks.store.clearToken).not.toHaveBeenCalled();
  });

  it('does not report authenticated after logout supersedes saved-token verification', async () => {
    // Regression for 57cfcdc6867f: a late positive verification cannot resurrect a logged-out session.
    let finishVerification!: (username: string | null) => void;
    mocks.verifyToken.mockImplementationOnce(() => new Promise((resolve) => {
      finishVerification = resolve;
    }));
    mocks.store.clearToken.mockImplementation(() => {
      mocks.store.readAndRepairToken.mockReturnValue(null as unknown as string);
    });
    const staleVerification = handler(IPC_CHANNELS.AUTH_GET_STATE)({}) as Promise<{
      isAuthenticated: boolean;
      username: string | null;
    }>;

    await handler(IPC_CHANNELS.AUTH_LOGOUT)({});
    finishVerification('old-dj');

    await expect(staleVerification).resolves.toMatchObject({
      isAuthenticated: false,
      username: null,
    });
    expect(mocks.store.clearToken).toHaveBeenCalledOnce();
  });
});

describe('bridge control IPC boundary', () => {
  it('starts with a valid event code and forwards credentials/settings', async () => {
    await handler(IPC_CHANNELS.BRIDGE_START)({}, 'AB12');

    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    expect(mocks.store.setLastEventCode).toHaveBeenCalledWith('AB12');
    expect(runner.start).toHaveBeenCalledWith({
      apiUrl: 'https://api.example.test',
      apiKey: 'bridge-key',
      eventCode: 'AB12',
      settings: DEFAULT_SETTINGS,
    });
  });

  it('does not start after logout invalidates an in-flight API-key lookup', async () => {
    // Regression coverage for 57cfcdc6867f: pending startup must not outlive logout.
    let resolveApiKey!: (key: string) => void;
    mocks.fetchBridgeApiKey.mockImplementationOnce(() => new Promise((resolve) => {
      resolveApiKey = resolve;
    }));

    const startRequest = handler(IPC_CHANNELS.BRIDGE_START)({}, 'AB12');
    await handler(IPC_CHANNELS.AUTH_LOGOUT)({});
    resolveApiKey('bridge-key');

    await expect(startRequest).rejects.toThrow('session changed');
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    expect(runner.start).not.toHaveBeenCalled();
    expect(mocks.store.clearToken).toHaveBeenCalledOnce();
  });

  it('does not start after an explicit stop invalidates an in-flight API-key lookup', async () => {
    let resolveApiKey!: (key: string) => void;
    mocks.fetchBridgeApiKey.mockImplementationOnce(() => new Promise((resolve) => {
      resolveApiKey = resolve;
    }));

    const startRequest = handler(IPC_CHANNELS.BRIDGE_START)({}, 'AB12');
    await handler(IPC_CHANNELS.BRIDGE_STOP)({});
    resolveApiKey('bridge-key');

    await expect(startRequest).rejects.toThrow('session changed');
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    expect(runner.start).not.toHaveBeenCalled();
    expect(runner.stop).toHaveBeenCalledOnce();
  });

  it('does not start with credentials captured before a new login', async () => {
    let resolveApiKey!: (key: string) => void;
    mocks.fetchBridgeApiKey.mockImplementationOnce(() => new Promise((resolve) => {
      resolveApiKey = resolve;
    }));

    const startRequest = handler(IPC_CHANNELS.BRIDGE_START)({}, 'AB12');
    await handler(IPC_CHANNELS.AUTH_LOGIN)({}, 'https://other.example', 'dj', 'secret');
    resolveApiKey('bridge-key');

    await expect(startRequest).rejects.toThrow('session changed');
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    expect(runner.start).not.toHaveBeenCalled();
    expect(mocks.store.setToken).toHaveBeenCalledWith('new-token');
  });

  it('rejects a new start while login is changing the authenticated session', async () => {
    let resolveLogin!: (result: { accessToken: string; username: string }) => void;
    mocks.login.mockImplementationOnce(() => new Promise((resolve) => {
      resolveLogin = resolve;
    }));

    const loginRequest = handler(IPC_CHANNELS.AUTH_LOGIN)({}, 'https://other.example', 'dj', 'secret');
    await expect(handler(IPC_CHANNELS.BRIDGE_START)({}, 'AB12'))
      .rejects.toThrow('login is in progress');
    expect(mocks.fetchBridgeApiKey).not.toHaveBeenCalled();

    resolveLogin({ accessToken: 'new-token', username: 'dj' });
    await loginRequest;
  });

  it.each(['API URL', 'token'])('rejects startup when the captured %s changes during key retrieval', async (credential) => {
    let resolveApiKey!: (key: string) => void;
    mocks.fetchBridgeApiKey.mockImplementationOnce(() => new Promise((resolve) => {
      resolveApiKey = resolve;
    }));

    const startRequest = handler(IPC_CHANNELS.BRIDGE_START)({}, 'AB12');
    if (credential === 'API URL') {
      mocks.store.getApiUrl.mockReturnValue('https://rotated.example');
    } else {
      mocks.store.readAndRepairToken.mockReturnValue('rotated-token');
    }
    resolveApiKey('bridge-key');

    await expect(startRequest).rejects.toThrow('session changed');
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    expect(runner.start).not.toHaveBeenCalled();
    expect(mocks.store.setLastEventCode).not.toHaveBeenCalled();
  });

  it('does not report startup success when stop supersedes an asynchronous runner start', async () => {
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    let resolveRunnerStart!: () => void;
    runner.start.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveRunnerStart = resolve;
    }));

    const startRequest = handler(IPC_CHANNELS.BRIDGE_START)({}, 'AB12');
    await vi.waitFor(() => expect(runner.start).toHaveBeenCalledOnce());
    await handler(IPC_CHANNELS.BRIDGE_STOP)({});
    resolveRunnerStart();

    await expect(startRequest).rejects.toThrow('session changed');
  });

  it('rejects a new start while logout is still stopping the previous bridge', async () => {
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    runner.isRunning = true;
    let resolveStop!: () => void;
    runner.stop.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveStop = resolve;
    }));

    const logoutRequest = handler(IPC_CHANNELS.AUTH_LOGOUT)({});
    await expect(handler(IPC_CHANNELS.BRIDGE_START)({}, 'AB12'))
      .rejects.toThrow('logout is in progress');
    expect(mocks.fetchBridgeApiKey).not.toHaveBeenCalled();

    resolveStop();
    await logoutRequest;
  });

  it.each(['ab12', 'ABC', 'ABCDEFGHIJK', 1234])('rejects invalid event code %p', async (eventCode) => {
    await expect(handler(IPC_CHANNELS.BRIDGE_START)({}, eventCode)).rejects.toThrow('Invalid event code');
    expect(mocks.fetchBridgeApiKey).not.toHaveBeenCalled();
  });

  it('rejects bridge start when no token is stored', async () => {
    mocks.store.readAndRepairToken.mockReturnValueOnce(null as unknown as string);

    await expect(handler(IPC_CHANNELS.BRIDGE_START)({}, 'AB12')).rejects.toThrow('Not authenticated');
    expect(mocks.fetchBridgeApiKey).not.toHaveBeenCalled();
  });

  it('forwards stop and admin commands to the bridge runner', async () => {
    await handler(IPC_CHANNELS.BRIDGE_STOP)({});
    await handler(IPC_CHANNELS.BRIDGE_RESET_DECKS)({});
    await handler(IPC_CHANNELS.BRIDGE_RECONNECT)({});
    await handler(IPC_CHANNELS.BRIDGE_RESTART)({});

    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    expect(runner.stop).toHaveBeenCalledOnce();
    expect(runner.resetDecks).toHaveBeenCalledOnce();
    expect(runner.reconnect).toHaveBeenCalledOnce();
    expect(runner.restartBridge).toHaveBeenCalledOnce();
  });

  it('forwards bridge stop failures to the renderer request boundary', async () => {
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    const cleanupError = new Error('device cleanup failed');
    runner.stop.mockRejectedValueOnce(cleanupError);

    await expect(handler(IPC_CHANNELS.BRIDGE_STOP)({})).rejects.toBe(cleanupError);
  });
});

describe('bridge:exportDebugReport IPC boundary', () => {
  it('cancels without reading or writing', async () => {
    mocks.dialog.showSaveDialog.mockResolvedValueOnce({ filePath: undefined });

    await expect(handler(IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT)({})).resolves.toBeNull();
    expect(mocks.readFile).not.toHaveBeenCalled();
    expect(mocks.writeFile).not.toHaveBeenCalled();
    expect(mocks.mkdtemp).not.toHaveBeenCalled();
  });

  it('uses the read fallback and awaits the report write', async () => {
    mocks.readFile.mockRejectedValue(Object.assign(new Error('missing log'), { code: 'ENOENT' }));
    let resolveWrite!: () => void;
    const writeCompleted = new Promise<void>((resolve) => {
      resolveWrite = resolve;
    });
    mocks.writeFile.mockImplementationOnce(async (...args) => {
      await writeCompleted;
      expect(args[1]).toEqual(expect.stringContaining('(no log file found)'));
    });

    const exportResult = handler(IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT)({}) as Promise<string>;
    let completed = false;
    void exportResult.then(() => {
      completed = true;
    });
    await vi.waitFor(() => expect(mocks.writeFile).toHaveBeenCalled());
    expect(completed).toBe(false);

    expect(mocks.writeFile).toHaveBeenCalledWith(
      '/tmp/.wrzdj-debug-report-unique/report.txt',
      expect.stringContaining('(no log file found)'),
      'utf-8',
    );
    expect(mocks.readFile).toHaveBeenCalledWith('/tmp/wrzdj.log', 'utf-8');

    resolveWrite();
    await expect(exportResult).resolves.toBe('/tmp/report.txt');
    expect(completed).toBe(true);
    expect(mocks.rename).toHaveBeenCalledWith(
      '/tmp/.wrzdj-debug-report-unique/report.txt',
      '/tmp/report.txt',
    );
    expect(mocks.rm).toHaveBeenCalledWith('/tmp/.wrzdj-debug-report-unique', {
      recursive: true,
      force: true,
    });
  });

  it('exports successful log contents and returns the selected path', async () => {
    await expect(handler(IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT)({})).resolves.toBe('/tmp/report.txt');

    expect(mocks.writeFile).toHaveBeenCalledWith(
      '/tmp/.wrzdj-debug-report-unique/report.txt',
      expect.stringContaining('bridge log'),
      'utf-8',
    );
  });

  it('propagates report write failures', async () => {
    mocks.writeFile.mockRejectedValueOnce(new Error('disk full'));

    await expect(handler(IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT)({})).rejects.toThrow('disk full');
  });

  it('reads the rotated log when the current log is absent', async () => {
    mocks.readFile.mockImplementation(async (path: string) => {
      if (path.endsWith('.1')) return 'rotated bridge log';
      throw Object.assign(new Error('missing current log'), { code: 'ENOENT' });
    });

    await handler(IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT)({});

    expect(mocks.writeFile).toHaveBeenCalledWith(
      '/tmp/.wrzdj-debug-report-unique/report.txt',
      expect.stringContaining('rotated bridge log'),
      'utf-8',
    );
    expect(mocks.readFile).toHaveBeenCalledTimes(2);
  });

  it('uses the no-log fallback when both current and rotated logs are absent', async () => {
    mocks.readFile.mockRejectedValue(Object.assign(new Error('missing'), { code: 'ENOENT' }));

    await handler(IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT)({});

    expect(mocks.writeFile).toHaveBeenCalledWith(
      '/tmp/.wrzdj-debug-report-unique/report.txt',
      expect.stringContaining('(no log file found)'),
      'utf-8',
    );
    expect(mocks.readFile).toHaveBeenCalledTimes(2);
  });
});

describe('IPC window lifecycle', () => {
  it('removes handlers and listeners when a window closes before reopening', () => {
    const firstSend = mainWindow.webContents.send;
    mainWindow.emit('closed');

    const secondWindow = Object.assign(new EventEmitter(), {
      isDestroyed: vi.fn(() => false),
      webContents: { send: vi.fn() },
    }) as TestWindow;
    registerIpcHandlers(secondWindow as never);
    const runner = getBridgeRunner() as unknown as InstanceType<typeof mocks.MockBridgeRunner>;
    runner.emit('statusChanged', { isRunning: false });

    expect(firstSend).not.toHaveBeenCalled();
    expect(secondWindow.webContents.send).toHaveBeenCalledOnce();
    secondWindow.emit('closed');
  });
});

describe('IPC handler accessors', () => {
  it('exposes the bridge runner and current log path', () => {
    expect(getBridgeRunner()).toBeDefined();
    expect(getLogFilePath()).toBe('/tmp/wrzdj.log');
  });
});
