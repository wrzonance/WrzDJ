import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  pluginStart: vi.fn(async () => {}),
  runtimeInstances: [] as unknown[],
  plugin: { info: { id: 'mock', name: 'Mock', description: 'Mock' } },
  checkEventHealth: vi.fn(),
  detectSubnetConflicts: vi.fn<() => unknown[]>(() => []),
  formatConflictWarnings: vi.fn<() => string[]>(() => []),
}));

type RuntimeSnapshot = {
  running: boolean;
  connectedDevice: string | null;
  pluginId: string;
  deckCount: number;
  circuitBreakerState: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
  bufferSize: number;
  uptimeSeconds: number;
  backendReachable: boolean;
  deckStates: never[];
};
type FakeRuntime = EventEmitter & {
  running: boolean;
  getSnapshot: (() => RuntimeSnapshot) & { mockReturnValue(value: RuntimeSnapshot): void };
  stop: ReturnType<typeof vi.fn>;
  resetDecks: ReturnType<typeof vi.fn>;
  reconnect: ReturnType<typeof vi.fn>;
  restart: ReturnType<typeof vi.fn>;
};

vi.mock('@wrzdj/bridge/electron', async () => {
  const { EventEmitter: RuntimeEmitter } = await import('node:events');
  class Runtime extends RuntimeEmitter {
    running = false;
    readonly getSnapshot = vi.fn(() => ({
      running: this.running,
      connectedDevice: null,
      pluginId: 'mock',
      deckCount: 0,
      circuitBreakerState: 'CLOSED' as const,
      bufferSize: 0,
      uptimeSeconds: 0,
      backendReachable: true,
      deckStates: [],
    }));
    readonly stop = vi.fn(async () => {
      this.running = false;
      this.emit('statusChanged', this.getSnapshot());
    });
    readonly resetDecks = vi.fn();
    readonly reconnect = vi.fn(async () => {});
    readonly restart = vi.fn(async () => {});

    constructor() {
      super();
      mocks.runtimeInstances.push(this);
    }

    async start(): Promise<void> {
      await mocks.pluginStart();
      this.running = true;
      this.emit('statusChanged', this.getSnapshot());
    }
  }
  class TestLogger {
    debug(): void {}
    info(): void {}
    warn(): void {}
    error(): void {}
  }
  return { BridgeRuntime: Runtime, getPlugin: () => mocks.plugin, Logger: TestLogger };
});
vi.mock('../event-health-service.js', () => ({ checkEventHealth: mocks.checkEventHealth }));
vi.mock('../network-check.js', () => ({
  detectSubnetConflicts: mocks.detectSubnetConflicts,
  formatConflictWarnings: mocks.formatConflictWarnings,
}));

import { BridgeRunner } from '../bridge-runner.js';
import type { BridgeRunnerConfig } from '../../shared/types.js';

const config: BridgeRunnerConfig = {
  apiUrl: 'https://api.wrzdj.com',
  apiKey: 'test-key',
  eventCode: 'ABC123',
  settings: {
    protocol: 'mock',
    liveThresholdSeconds: 15,
    pauseGraceSeconds: 3,
    nowPlayingPauseSeconds: 10,
    useFaderDetection: false,
    masterDeckPriority: false,
    minPlaySeconds: 5,
  },
};

describe('BridgeRunner runtime adapter', () => {
  let runner: BridgeRunner;

  beforeEach(() => {
    vi.useFakeTimers();
    mocks.runtimeInstances.length = 0;
    vi.clearAllMocks();
    mocks.pluginStart.mockResolvedValue(undefined);
    mocks.checkEventHealth.mockResolvedValue('active');
    mocks.detectSubnetConflicts.mockReturnValue([]);
    mocks.formatConflictWarnings.mockReturnValue([]);
    runner = new BridgeRunner();
  });

  afterEach(async () => {
    await runner.stop().catch(() => {});
    vi.useRealTimers();
  });

  it('preserves the status and log contract through the shared runtime', async () => {
    const statuses: Array<{ isRunning: boolean; eventCode: string | null }> = [];
    const logs: Array<{ message: string; level: string }> = [];
    runner.on('statusChanged', (status) => statuses.push(status));
    runner.on('log', (entry) => logs.push(entry));

    await runner.start(config);
    const runtime = mocks.runtimeInstances[0] as FakeRuntime;
    runtime.getSnapshot.mockReturnValue({
      ...runtime.getSnapshot(), backendReachable: false, bufferSize: 2,
    });
    runtime.emit('statusChanged', runtime.getSnapshot());
    runtime.emit('log', { message: 'runtime diagnostic', level: 'warn' });

    expect(runner.getStatus()).toMatchObject({
      isRunning: true,
      eventCode: 'ABC123',
      stopReason: null,
      pluginId: 'mock',
      backendReachable: false,
      bufferSize: 2,
    });
    expect(statuses.some((status) => status.isRunning && status.eventCode === 'ABC123')).toBe(true);
    expect(logs).toContainEqual({ message: 'runtime diagnostic', level: 'warn' });
  });

  it('reports runtime cleanup failures after updating the adapter state', async () => {
    // Regression coverage for 57cfcdc6867f: propagate cleanup failures so IPC and restart callers cannot report success.
    const logs: Array<{ message: string; level: string }> = [];
    runner.on('log', (entry) => logs.push(entry));
    await runner.start(config);
    const runtime = mocks.runtimeInstances[0] as FakeRuntime;
    const cleanupError = new Error('device cleanup failed');
    runtime.stop.mockRejectedValueOnce(cleanupError);

    await expect(runner.stop()).rejects.toBe(cleanupError);

    expect(runner.getStatus().isRunning).toBe(false);
    expect(logs).toContainEqual({ message: 'Bridge shutdown failed: device cleanup failed', level: 'error' });
  });

  it('does not start a replacement session when shutdown fails during restart', async () => {
    await runner.start(config);
    const runtime = mocks.runtimeInstances[0] as FakeRuntime;
    runtime.stop.mockRejectedValueOnce(new Error('device cleanup failed'));

    await expect(runner.restartBridge()).rejects.toThrow('device cleanup failed');

    expect(mocks.runtimeInstances).toHaveLength(1);
    expect(mocks.pluginStart).toHaveBeenCalledTimes(1);
  });

  it('handles cleanup failures from automatic authentication shutdown', async () => {
    // Regression coverage for 57cfcdc6867f: background stop launches must observe rejection after stop begins propagating it.
    const logs: Array<{ message: string; level: string }> = [];
    runner.on('log', (entry) => logs.push(entry));
    await runner.start(config);
    const runtime = mocks.runtimeInstances[0] as FakeRuntime;
    runtime.stop.mockRejectedValueOnce(new Error('device cleanup failed'));

    runtime.emit('authenticationError');
    await vi.advanceTimersByTimeAsync(0);

    expect(logs).toContainEqual({ message: 'Bridge shutdown failed: device cleanup failed', level: 'error' });
    expect(logs).toContainEqual({ message: 'Automatic bridge shutdown failed: device cleanup failed', level: 'error' });
  });

  it('handles cleanup failures from automatic health-check shutdown', async () => {
    const logs: Array<{ message: string; level: string }> = [];
    runner.on('log', (entry) => logs.push(entry));
    await runner.start(config);
    const runtime = mocks.runtimeInstances[0] as FakeRuntime;
    runtime.stop.mockRejectedValueOnce(new Error('device cleanup failed'));
    mocks.checkEventHealth.mockResolvedValueOnce('expired');

    await vi.advanceTimersByTimeAsync(30_000);

    expect(logs).toContainEqual({ message: 'Bridge shutdown failed: device cleanup failed', level: 'error' });
    expect(logs).toContainEqual({ message: 'Event health check failed: device cleanup failed', level: 'error' });
  });

  it('projects runtime connection and track events to app status', async () => {
    await runner.start(config);
    const runtime = mocks.runtimeInstances[0] as FakeRuntime;
    runtime.emit('connection', { connected: true, deviceName: 'Player 1' });
    runtime.emit('deckLive', {
      deckId: '1', track: { title: 'Strobe', artist: 'deadmau5', album: 'Album' },
    });

    expect(runner.getStatus().connectedDevice).toBe('Player 1');
    expect(runner.getStatus().currentTrack).toMatchObject({ title: 'Strobe', deckId: '1' });
    runtime.emit('clearNowPlaying');
    expect(runner.getStatus().currentTrack).toBeNull();
  });

  it('keeps the active runtime callbacks after rejecting a duplicate start', async () => {
    await runner.start(config);
    const runtime = mocks.runtimeInstances[0] as FakeRuntime;

    await expect(runner.start(config)).rejects.toThrow('Bridge is already running');
    runtime.emit('connection', { connected: true, deviceName: 'Player 1' });

    expect(runner.getStatus()).toMatchObject({
      isRunning: true,
      connectedDevice: 'Player 1',
    });
    expect(mocks.runtimeInstances).toHaveLength(1);
  });

  it('stops the session on deleted or expired events and ignores transient health errors', async () => {
    await runner.start(config);
    mocks.checkEventHealth.mockResolvedValueOnce('error').mockResolvedValueOnce('expired');
    await vi.advanceTimersByTimeAsync(30_000);
    expect(runner.isRunning).toBe(true);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(runner.getStatus()).toMatchObject({ isRunning: false, stopReason: 'Event expired or archived' });
  });

  it('stops when an event is deleted and clears the reason and network warnings on the next start', async () => {
    mocks.detectSubnetConflicts.mockReturnValue([{}]);
    mocks.formatConflictWarnings.mockReturnValue(['Conflict warning']);
    await runner.start(config);
    mocks.checkEventHealth.mockResolvedValueOnce('not_found');
    await vi.advanceTimersByTimeAsync(30_000);
    expect(runner.getStatus()).toMatchObject({ isRunning: false, stopReason: 'Event was deleted' });

    mocks.detectSubnetConflicts.mockReturnValue([]);
    await runner.start(config);
    expect(runner.getStatus()).toMatchObject({ isRunning: true, stopReason: null, networkWarnings: [] });
  });

  it('keeps a healthy event running and removes the health timer when stopped', async () => {
    await runner.start(config);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(runner.isRunning).toBe(true);
    expect(mocks.checkEventHealth).toHaveBeenCalledOnce();

    await runner.stop();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(mocks.checkEventHealth).toHaveBeenCalledOnce();
  });

  it('does not start health polling when stopped during runtime startup', async () => {
    let finishStart!: () => void;
    mocks.pluginStart.mockImplementationOnce(() => new Promise<void>((resolve) => { finishStart = resolve; }));
    const starting = runner.start(config);
    await Promise.resolve();
    const runtime = mocks.runtimeInstances[0] as FakeRuntime;
    await runner.stop();
    finishStart();
    await starting;

    expect(runner.isRunning).toBe(false);
    expect(runtime.stop).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancels a new start waiting for shutdown when another stop arrives', async () => {
    await runner.start(config);
    const oldRuntime = mocks.runtimeInstances[0] as FakeRuntime;
    let finishStop!: () => void;
    oldRuntime.stop.mockImplementationOnce(async () => {
      await new Promise<void>((resolve) => { finishStop = resolve; });
      oldRuntime.running = false;
    });

    const stopping = runner.stop();
    expect(runner.isRunning).toBe(false);
    const pendingStart = runner.start({ ...config, eventCode: 'XYZ789' });

    // A logout can call stop while the prior device teardown is still pending.
    const supersedingStop = runner.stop();
    finishStop();
    await Promise.all([stopping, supersedingStop]);

    await expect(pendingStart).rejects.toThrow('cancelled');
    expect(mocks.runtimeInstances).toHaveLength(1);
    expect(runner.isRunning).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('surfaces runtime startup errors and clears adapter state', async () => {
    mocks.pluginStart.mockRejectedValueOnce(new Error('equipment unavailable'));
    await expect(runner.start(config)).rejects.toThrow('equipment unavailable');
    expect(runner.getStatus()).toMatchObject({ isRunning: false, pluginId: null });
    expect(vi.getTimerCount()).toBe(0);
  });

  it('stops on a runtime authentication-expiry signal without marking the backend unreachable', async () => {
    await runner.start(config);
    const runtime = mocks.runtimeInstances[0] as FakeRuntime;
    runtime.getSnapshot.mockReturnValue({ ...runtime.getSnapshot(), backendReachable: true });
    runtime.emit('authenticationError');
    await vi.advanceTimersByTimeAsync(0);
    expect(runner.getStatus()).toMatchObject({
      isRunning: false,
      backendReachable: true,
      stopReason: 'Session expired — please log in again',
    });
  });

  it('ignores a delayed authentication-expiry callback from a stopped runtime', async () => {
    await runner.start(config);
    const oldRuntime = mocks.runtimeInstances[0] as FakeRuntime;
    oldRuntime.emit('authenticationError');
    await runner.stop();
    await runner.start(config);

    await vi.advanceTimersByTimeAsync(0);

    expect(runner.getStatus()).toMatchObject({ isRunning: true, stopReason: null });
  });

  it('ignores an event-health result that belongs to a stopped runtime', async () => {
    await runner.start(config);
    let finishHealth!: (status: string) => void;
    mocks.checkEventHealth.mockImplementationOnce(() => new Promise<string>((resolve) => { finishHealth = resolve; }));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(mocks.checkEventHealth).toHaveBeenCalledOnce();

    await runner.stop();
    await runner.start(config);
    finishHealth('not_found');
    await Promise.resolve();

    expect(runner.getStatus()).toMatchObject({ isRunning: true, stopReason: null });
  });

  it('does not let an old startup rejection clear a newer runtime session', async () => {
    let rejectOldStart!: (error: Error) => void;
    mocks.pluginStart.mockImplementationOnce(() => new Promise<void>((_resolve, reject) => { rejectOldStart = reject; }));
    const oldStart = runner.start(config);
    await Promise.resolve();
    await runner.stop();
    await runner.start(config);
    rejectOldStart(new Error('late startup failure'));

    await expect(oldStart).rejects.toThrow('late startup failure');
    expect(runner.isRunning).toBe(true);
    expect((mocks.runtimeInstances[1] as FakeRuntime).running).toBe(true);
  });

  it('keeps event health and network diagnostics in the Electron adapter', async () => {
    mocks.detectSubnetConflicts.mockReturnValue([{}]);
    mocks.formatConflictWarnings.mockReturnValue(['Conflict warning']);
    await runner.start(config);
    expect(runner.getStatus().networkWarnings).toEqual(['Conflict warning']);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(mocks.checkEventHealth).toHaveBeenCalledWith(config.apiUrl, config.eventCode);
  });

  it('delegates equipment controls and restarts only after stopping the old runtime', async () => {
    await runner.start(config);
    const first = mocks.runtimeInstances[0] as FakeRuntime;
    runner.resetDecks();
    await runner.reconnect();
    await runner.restartBridge();

    expect(first.resetDecks).toHaveBeenCalledOnce();
    expect(first.reconnect).toHaveBeenCalledOnce();
    expect(first.stop).toHaveBeenCalledOnce();
    expect(mocks.runtimeInstances).toHaveLength(2);
    expect(runner.isRunning).toBe(true);
  });

});
