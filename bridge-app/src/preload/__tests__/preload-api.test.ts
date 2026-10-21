import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BridgeApi } from '../../shared/bridge-api.js';
import { IPC_CHANNELS } from '../../shared/types.js';

const mocks = vi.hoisted(() => ({
  expose: vi.fn(),
  invoke: vi.fn(),
  on: vi.fn(),
  removeListener: vi.fn(),
}));

vi.mock('electron', () => ({
  contextBridge: { exposeInMainWorld: mocks.expose },
  ipcRenderer: {
    invoke: mocks.invoke,
    on: mocks.on,
    removeListener: mocks.removeListener,
  },
}));

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  mocks.invoke.mockResolvedValue(undefined);
});

describe('preload BridgeApi', () => {
  it('exposes methods that map to the expected IPC channels and arguments', async () => {
    await import('../preload.js');
    const api = mocks.expose.mock.calls[0][1] as BridgeApi;

    await api.login('https://api.example.test', 'dj', 'secret');
    await api.startBridge('EVENT1');
    await api.updateSettings({ liveThresholdSeconds: 20 });
    await api.getSettings();

    expect(mocks.invoke).toHaveBeenNthCalledWith(
      1,
      IPC_CHANNELS.AUTH_LOGIN,
      'https://api.example.test',
      'dj',
      'secret',
    );
    expect(mocks.invoke).toHaveBeenNthCalledWith(2, IPC_CHANNELS.BRIDGE_START, 'EVENT1');
    expect(mocks.invoke).toHaveBeenNthCalledWith(
      3,
      IPC_CHANNELS.SETTINGS_UPDATE,
      { liveThresholdSeconds: 20 },
    );
    expect(mocks.invoke).toHaveBeenNthCalledWith(4, IPC_CHANNELS.SETTINGS_GET);
  });

  it('unwraps subscription payloads and removes the exact listener on cleanup', async () => {
    await import('../preload.js');
    const api = mocks.expose.mock.calls[0][1] as BridgeApi;
    const callback = vi.fn();
    const unsubscribe = api.onPing(callback);
    const listener = mocks.on.mock.calls[0][1];

    listener({}, 'ignored');
    expect(callback).toHaveBeenCalledOnce();
    unsubscribe();
    expect(mocks.removeListener).toHaveBeenCalledWith(IPC_CHANNELS.BRIDGE_PING, listener);
  });
});
