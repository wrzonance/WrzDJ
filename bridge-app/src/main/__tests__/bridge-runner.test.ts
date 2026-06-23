import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the plugin system before importing BridgeRunner
vi.mock('@bridge/plugin-bridge.js', () => {
  const { EventEmitter } = require('events');
  class MockPluginBridge extends EventEmitter {
    private _running = false;
    manager = new EventEmitter();
    constructor() {
      super();
      this.manager.getDeckIds = () => [];
      this.manager.getDeckState = () => ({});
      this.manager.destroy = vi.fn();
    }
    get isRunning() { return this._running; }
    async start() { this._running = true; }
    async stop() { this._running = false; }
  }
  return { PluginBridge: MockPluginBridge };
});

vi.mock('@bridge/plugin-registry.js', () => {
  const { EventEmitter } = require('events');
  return {
    getPlugin: vi.fn(() => {
      const plugin = new EventEmitter();
      Object.assign(plugin, {
        info: { id: 'mock', name: 'Mock', description: 'Mock plugin' },
        capabilities: {
          multiDeck: false,
          playState: false,
          faderLevel: false,
          masterDeck: false,
          albumMetadata: false,
        },
        isRunning: false,
        start: vi.fn(async () => {}),
        stop: vi.fn(async () => {}),
      });
      return plugin;
    }),
  };
});

vi.mock('@bridge/plugins/index.js', () => ({}));

// Mock the health check service
vi.mock('../event-health-service.js', () => ({
  checkEventHealth: vi.fn(),
}));

// Mock network check — default to no conflicts
vi.mock('../network-check.js', () => ({
  detectSubnetConflicts: vi.fn(() => []),
  formatConflictWarnings: vi.fn(() => []),
}));

// Mock fetch for postBridgeStatus calls
const mockFetch = vi.fn().mockResolvedValue({ ok: true, text: () => Promise.resolve('') });
global.fetch = mockFetch;

import { BridgeRunner } from '../bridge-runner.js';
import { checkEventHealth } from '../event-health-service.js';
import { detectSubnetConflicts, formatConflictWarnings } from '../network-check.js';
import type { BridgeRunnerConfig } from '../../shared/types.js';

const mockedCheckEventHealth = vi.mocked(checkEventHealth);
const mockedDetectSubnetConflicts = vi.mocked(detectSubnetConflicts);
const mockedFormatConflictWarnings = vi.mocked(formatConflictWarnings);

const TEST_CONFIG: BridgeRunnerConfig = {
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

describe('BridgeRunner', () => {
  let runner: BridgeRunner;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mockedCheckEventHealth.mockResolvedValue('active');
    runner = new BridgeRunner();
  });

  afterEach(async () => {
    if (runner.isRunning) {
      await runner.stop();
    }
    vi.useRealTimers();
  });

  it('starts and stops cleanly', async () => {
    await runner.start(TEST_CONFIG);
    expect(runner.isRunning).toBe(true);

    const status = runner.getStatus();
    expect(status.eventCode).toBe('ABC123');
    expect(status.stopReason).toBeNull();

    await runner.stop();
    expect(runner.isRunning).toBe(false);
  });

  it('includes stopReason as null initially', async () => {
    const status = runner.getStatus();
    expect(status.stopReason).toBeNull();
  });

  it('sets stopReason when stopped with a reason', async () => {
    await runner.start(TEST_CONFIG);
    await runner.stop('Event was deleted');

    const status = runner.getStatus();
    expect(status.stopReason).toBe('Event was deleted');
    expect(status.isRunning).toBe(false);
  });

  it('clears stopReason on next start', async () => {
    await runner.start(TEST_CONFIG);
    await runner.stop('Event was deleted');
    expect(runner.getStatus().stopReason).toBe('Event was deleted');

    await runner.start(TEST_CONFIG);
    expect(runner.getStatus().stopReason).toBeNull();
  });

  it('auto-stops when health check returns not_found', async () => {
    await runner.start(TEST_CONFIG);
    expect(runner.isRunning).toBe(true);

    mockedCheckEventHealth.mockResolvedValue('not_found');

    // Advance timer to trigger health check
    await vi.advanceTimersByTimeAsync(30_000);

    expect(runner.isRunning).toBe(false);
    expect(runner.getStatus().stopReason).toBe('Event was deleted');
  });

  it('auto-stops when health check returns expired', async () => {
    await runner.start(TEST_CONFIG);
    expect(runner.isRunning).toBe(true);

    mockedCheckEventHealth.mockResolvedValue('expired');

    await vi.advanceTimersByTimeAsync(30_000);

    expect(runner.isRunning).toBe(false);
    expect(runner.getStatus().stopReason).toBe('Event expired or archived');
  });

  it('does not stop on health check error (transient failure)', async () => {
    await runner.start(TEST_CONFIG);
    expect(runner.isRunning).toBe(true);

    mockedCheckEventHealth.mockResolvedValue('error');

    await vi.advanceTimersByTimeAsync(30_000);

    expect(runner.isRunning).toBe(true);
    expect(runner.getStatus().stopReason).toBeNull();
  });

  it('does not stop when health check returns active', async () => {
    await runner.start(TEST_CONFIG);
    expect(runner.isRunning).toBe(true);

    mockedCheckEventHealth.mockResolvedValue('active');

    await vi.advanceTimersByTimeAsync(30_000);

    expect(runner.isRunning).toBe(true);
  });

  it('health check is called with correct arguments', async () => {
    await runner.start(TEST_CONFIG);

    await vi.advanceTimersByTimeAsync(30_000);

    expect(mockedCheckEventHealth).toHaveBeenCalledWith(
      'https://api.wrzdj.com',
      'ABC123',
    );
  });

  it('stops health check timer when bridge is stopped', async () => {
    await runner.start(TEST_CONFIG);
    await runner.stop();

    mockedCheckEventHealth.mockResolvedValue('not_found');
    await vi.advanceTimersByTimeAsync(60_000);

    // Health check should not have been called after stop
    expect(mockedCheckEventHealth).not.toHaveBeenCalled();
  });

  it('emits statusChanged with stopReason on auto-stop', async () => {
    const statusChanges: Array<{ isRunning: boolean; stopReason: string | null }> = [];
    runner.on('statusChanged', (status) => {
      statusChanges.push({ isRunning: status.isRunning, stopReason: status.stopReason });
    });

    await runner.start(TEST_CONFIG);
    mockedCheckEventHealth.mockResolvedValue('not_found');
    await vi.advanceTimersByTimeAsync(30_000);

    const lastStatus = statusChanges[statusChanges.length - 1];
    expect(lastStatus.isRunning).toBe(false);
    expect(lastStatus.stopReason).toBe('Event was deleted');
  });

  it('includes empty networkWarnings when no conflicts', async () => {
    await runner.start(TEST_CONFIG);
    const status = runner.getStatus();
    expect(status.networkWarnings).toEqual([]);
  });

  it('includes networkWarnings when subnet conflicts detected', async () => {
    mockedDetectSubnetConflicts.mockReturnValue([
      {
        subnet: '192.168.1.0/24',
        interfaces: [
          { name: 'eth0', address: '192.168.1.100' },
          { name: 'wlan0', address: '192.168.1.200' },
        ],
      },
    ]);
    mockedFormatConflictWarnings.mockReturnValue([
      'Multiple interfaces on subnet 192.168.1.0/24: eth0 (192.168.1.100), wlan0 (192.168.1.200). This may cause DJ equipment connection failures — consider disabling one interface.',
    ]);

    await runner.start(TEST_CONFIG);
    const status = runner.getStatus();
    expect(status.networkWarnings).toHaveLength(1);
    expect(status.networkWarnings[0]).toContain('192.168.1.0/24');
  });

  it('clears networkWarnings on restart', async () => {
    mockedDetectSubnetConflicts.mockReturnValueOnce([
      {
        subnet: '192.168.1.0/24',
        interfaces: [
          { name: 'eth0', address: '192.168.1.100' },
          { name: 'wlan0', address: '192.168.1.200' },
        ],
      },
    ]);
    mockedFormatConflictWarnings.mockReturnValueOnce(['Warning message']);

    await runner.start(TEST_CONFIG);
    expect(runner.getStatus().networkWarnings).toHaveLength(1);

    await runner.stop();

    // Second start with no conflicts
    mockedDetectSubnetConflicts.mockReturnValue([]);
    mockedFormatConflictWarnings.mockReturnValue([]);

    await runner.start(TEST_CONFIG);
    expect(runner.getStatus().networkWarnings).toEqual([]);
  });

  it('calls DELETE /bridge/nowplaying/{code} on stop', async () => {
    await runner.start(TEST_CONFIG);
    mockFetch.mockClear();

    await runner.stop();

    // Should have called DELETE /bridge/nowplaying/ABC123 and POST /bridge/status
    const deleteCall = mockFetch.mock.calls.find(
      (call) => typeof call[0] === 'string' && call[0].includes('/bridge/nowplaying/') && call[1]?.method === 'DELETE',
    );
    expect(deleteCall).toBeDefined();
    expect(deleteCall![0]).toContain('/bridge/nowplaying/ABC123');
  });

  it('logs networkWarnings when conflicts detected', async () => {
    const logs: Array<{ message: string; level: string }> = [];
    runner.on('log', (msg: { message: string; level: string }) => logs.push(msg));

    mockedDetectSubnetConflicts.mockReturnValue([
      {
        subnet: '192.168.1.0/24',
        interfaces: [
          { name: 'eth0', address: '192.168.1.100' },
          { name: 'wlan0', address: '192.168.1.200' },
        ],
      },
    ]);
    mockedFormatConflictWarnings.mockReturnValue(['Conflict warning text']);

    await runner.start(TEST_CONFIG);

    expect(logs.some((l) => l.message.includes('Conflict warning text') && l.level === 'warn')).toBe(true);
  });

  it('sets backendReachable to false after all retries exhausted', async () => {
    await runner.start(TEST_CONFIG);
    expect(runner.getStatus().backendReachable).toBe(true);

    // Make all POST attempts fail
    mockFetch.mockRejectedValue(new Error('Network error'));

    // Trigger a POST by emitting a connection event on the pluginBridge
    const pluginBridge = (runner as unknown as Record<string, unknown>).pluginBridge as {
      emit: (event: string, ...args: unknown[]) => boolean;
    };
    pluginBridge.emit('connection', { connected: true, deviceName: 'Test Device' });

    // Let all retries execute (3 retries: 2s + 4s + 8s = 14s)
    await vi.advanceTimersByTimeAsync(20_000);

    expect(runner.getStatus().backendReachable).toBe(false);

    // Restore mock before afterEach cleanup calls stop()
    mockFetch.mockResolvedValue({ ok: true, text: () => Promise.resolve('') });
  });

  it('restores backendReachable to true on successful POST after failure', async () => {
    await runner.start(TEST_CONFIG);

    // Make all attempts fail
    mockFetch.mockRejectedValue(new Error('Network error'));

    const pluginBridge = (runner as unknown as Record<string, unknown>).pluginBridge as {
      emit: (event: string, ...args: unknown[]) => boolean;
    };
    pluginBridge.emit('connection', { connected: true, deviceName: 'Test Device' });

    await vi.advanceTimersByTimeAsync(20_000);
    expect(runner.getStatus().backendReachable).toBe(false);

    // Now make fetch succeed again
    mockFetch.mockResolvedValue({ ok: true, text: () => Promise.resolve('') });
    pluginBridge.emit('connection', { connected: false });

    await vi.advanceTimersByTimeAsync(1_000);
    expect(runner.getStatus().backendReachable).toBe(true);
  });

  it('includes backendReachable: true by default', async () => {
    const status = runner.getStatus();
    expect(status.backendReachable).toBe(true);
  });

  it('posts now playing when deckLive event fires', async () => {
    await runner.start(TEST_CONFIG);
    mockFetch.mockClear();

    const pluginBridge = (runner as unknown as Record<string, unknown>).pluginBridge as {
      emit: (event: string, ...args: unknown[]) => boolean;
    };
    pluginBridge.emit('deckLive', {
      deckId: '1',
      track: { title: 'Strobe', artist: 'deadmau5', album: 'For Lack of a Better Name' },
    });

    await vi.advanceTimersByTimeAsync(100);

    const nowPlayingCall = mockFetch.mock.calls.find(
      (call) => typeof call[0] === 'string' && call[0].includes('/bridge/nowplaying') && call[1]?.method !== 'DELETE',
    );
    expect(nowPlayingCall).toBeDefined();
    const body = JSON.parse(nowPlayingCall![1].body as string);
    expect(body.title).toBe('Strobe');
    expect(body.artist).toBe('deadmau5');
    expect(body.event_code).toBe('ABC123');
  });

  it('skips duplicate track (deduplication)', async () => {
    await runner.start(TEST_CONFIG);

    const pluginBridge = (runner as unknown as Record<string, unknown>).pluginBridge as {
      emit: (event: string, ...args: unknown[]) => boolean;
    };

    // First track
    pluginBridge.emit('deckLive', {
      deckId: '1',
      track: { title: 'Strobe', artist: 'deadmau5' },
    });
    await vi.advanceTimersByTimeAsync(100);

    mockFetch.mockClear();

    // Same track again — should be skipped
    pluginBridge.emit('deckLive', {
      deckId: '1',
      track: { title: 'Strobe', artist: 'deadmau5' },
    });
    await vi.advanceTimersByTimeAsync(100);

    const nowPlayingCalls = mockFetch.mock.calls.filter(
      (call) => typeof call[0] === 'string' && call[0].includes('/bridge/nowplaying') && call[1]?.method !== 'DELETE',
    );
    expect(nowPlayingCalls).toHaveLength(0);
  });

  it('skips track with empty title', async () => {
    await runner.start(TEST_CONFIG);
    mockFetch.mockClear();

    const pluginBridge = (runner as unknown as Record<string, unknown>).pluginBridge as {
      emit: (event: string, ...args: unknown[]) => boolean;
    };
    pluginBridge.emit('deckLive', {
      deckId: '1',
      track: { title: '', artist: 'deadmau5' },
    });
    await vi.advanceTimersByTimeAsync(100);

    const nowPlayingCalls = mockFetch.mock.calls.filter(
      (call) => typeof call[0] === 'string' && call[0].includes('/bridge/nowplaying') && call[1]?.method !== 'DELETE',
    );
    expect(nowPlayingCalls).toHaveLength(0);
  });

  it('track posting continues when network fails (retries)', async () => {
    await runner.start(TEST_CONFIG);

    // Make fetch fail temporarily
    mockFetch.mockRejectedValueOnce(new Error('Network error'))
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValue({ ok: true, text: () => Promise.resolve('') });

    const pluginBridge = (runner as unknown as Record<string, unknown>).pluginBridge as {
      emit: (event: string, ...args: unknown[]) => boolean;
    };
    pluginBridge.emit('deckLive', {
      deckId: '1',
      track: { title: 'Test Track', artist: 'Test Artist' },
    });

    // Let retries execute (2s + 4s)
    await vi.advanceTimersByTimeAsync(10_000);

    // After retries succeed, backendReachable should still be true
    expect(runner.getStatus().backendReachable).toBe(true);
  });

  it('clears currentTrack on clearNowPlaying event', async () => {
    await runner.start(TEST_CONFIG);

    const pluginBridge = (runner as unknown as Record<string, unknown>).pluginBridge as {
      emit: (event: string, ...args: unknown[]) => boolean;
    };

    // First set a track
    pluginBridge.emit('deckLive', {
      deckId: '1',
      track: { title: 'Strobe', artist: 'deadmau5' },
    });
    await vi.advanceTimersByTimeAsync(100);
    expect(runner.getStatus().currentTrack).not.toBeNull();

    mockFetch.mockClear();

    // Clear now playing
    pluginBridge.emit('clearNowPlaying');
    await vi.advanceTimersByTimeAsync(100);

    expect(runner.getStatus().currentTrack).toBeNull();
  });

  it('cascade: transient error → continues → expired → stops', async () => {
    await runner.start(TEST_CONFIG);
    expect(runner.isRunning).toBe(true);

    // First health check: transient error — should continue
    mockedCheckEventHealth.mockResolvedValue('error');
    await vi.advanceTimersByTimeAsync(30_000);
    expect(runner.isRunning).toBe(true);
    expect(runner.getStatus().stopReason).toBeNull();

    // Second health check: expired — should stop
    mockedCheckEventHealth.mockResolvedValue('expired');
    await vi.advanceTimersByTimeAsync(30_000);
    expect(runner.isRunning).toBe(false);
    expect(runner.getStatus().stopReason).toBe('Event expired or archived');
  });

  it('throws when starting while already running', async () => {
    await runner.start(TEST_CONFIG);
    await expect(runner.start(TEST_CONFIG)).rejects.toThrow('already running');
  });

  it('buffers failed now-playing tracks for replay', async () => {
    await runner.start(TEST_CONFIG);

    // Make fetch fail
    mockFetch.mockRejectedValue(new Error('Network error'));

    const pluginBridge = (runner as unknown as Record<string, unknown>).pluginBridge as {
      emit: (event: string, ...args: unknown[]) => boolean;
    };
    pluginBridge.emit('deckLive', {
      deckId: '1',
      track: { title: 'Lost Track', artist: 'Lost Artist' },
    });

    // Let retries exhaust (2s + 4s + 8s)
    await vi.advanceTimersByTimeAsync(20_000);

    // Log should mention buffering
    const logs: Array<{ message: string; level: string }> = [];
    runner.on('log', (msg: { message: string; level: string }) => logs.push(msg));

    // Emit another track to trigger more buffer logs
    pluginBridge.emit('deckLive', {
      deckId: '2',
      track: { title: 'Another Lost Track', artist: 'Another Artist' },
    });
    await vi.advanceTimersByTimeAsync(20_000);

    expect(logs.some((l) => l.message.includes('Buffered track for replay'))).toBe(true);

    // Restore mock before cleanup
    mockFetch.mockResolvedValue({ ok: true, text: () => Promise.resolve('') });
  });

  it('emits log events with level', async () => {
    const logs: Array<{ message: string; level: string }> = [];
    runner.on('log', (msg: { message: string; level: string }) => logs.push(msg));

    await runner.start(TEST_CONFIG);

    expect(logs.some((l) => l.message.includes('Starting bridge') && l.level === 'info')).toBe(true);
    expect(logs.some((l) => l.message.includes('ABC123'))).toBe(true);
  });

  it('stops the bridge on a 401 without retrying or recording a circuit failure', async () => {
    await runner.start(TEST_CONFIG);
    expect(runner.getStatus().backendReachable).toBe(true);

    // Spy on the private circuit breaker so we can prove a 401 is treated as an
    // auth problem, NOT a backend-availability failure.
    const circuitBreaker = (runner as unknown as Record<string, unknown>).circuitBreaker as {
      recordFailure: () => void;
      recordSuccess: () => void;
    };
    const recordFailure = vi.spyOn(circuitBreaker, 'recordFailure');
    const stopSpy = vi.spyOn(runner, 'stop');

    // Only the FIRST POST gets a 401 (expired session token); the deferred
    // shutdown status-POST that stop() issues succeeds, so it can't be confused
    // for a retry of the 401'd request.
    mockFetch.mockClear();
    mockFetch
      .mockResolvedValueOnce({ status: 401, ok: false, text: () => Promise.resolve('') })
      .mockResolvedValue({ ok: true, text: () => Promise.resolve('') });

    // A connection event triggers postBridgeStatus → postWithRetry.
    const pluginBridge = (runner as unknown as Record<string, unknown>).pluginBridge as {
      emit: (event: string, ...args: unknown[]) => boolean;
    };
    pluginBridge.emit('connection', { connected: true, deviceName: 'Test Device' });

    // Resolve the 401 POST only — the retry loop returns immediately on 401 with
    // NO backoff sleep, so a single microtask flush is enough to settle it.
    await Promise.resolve();
    await Promise.resolve();

    const statusPostsBeforeStop = mockFetch.mock.calls.filter(
      (call) =>
        typeof call[0] === 'string' &&
        call[0].includes('/bridge/status') &&
        call[1]?.method === 'POST',
    );
    // Exactly one status POST — the 401 short-circuited the loop (no 2s/4s/8s retry).
    expect(statusPostsBeforeStop).toHaveLength(1);

    // Advancing through the full retry window must NOT produce a retry of that POST.
    await vi.advanceTimersByTimeAsync(20_000);

    // 401 is an auth problem — it must NOT count as a circuit/backend failure,
    // and backendReachable must be left untouched (no false "backend down").
    expect(recordFailure).not.toHaveBeenCalled();
    expect(runner.getStatus().backendReachable).toBe(true);

    // The bridge is stopped with the session-expiry reason.
    expect(stopSpy).toHaveBeenCalledWith('Session expired — please log in again');
    expect(runner.isRunning).toBe(false);
    expect(runner.getStatus().stopReason).toBe('Session expired — please log in again');

    // Restore mock before afterEach cleanup.
    mockFetch.mockResolvedValue({ ok: true, text: () => Promise.resolve('') });
  });

  it('logs setbuilder transport command payloads from the command poller', () => {
    const logs: Array<{ message: string; level: string }> = [];
    runner.on('log', (msg: { message: string; level: string }) => logs.push(msg));
    const handleCommand = (
      runner as unknown as {
        handleCommand: (type: string, command?: { payload?: Record<string, unknown> }) => void;
      }
    ).handleCommand.bind(runner);

    handleCommand('setbuilder_transport', {
      payload: { action: 'play', title: 'Track A', position_sec: 12.25 },
    });
    handleCommand('setbuilder_transport');

    expect(
      logs.some(
        (l) =>
          l.level === 'info' &&
          l.message === 'Setbuilder transport command received: play "Track A" @ 12.3s',
      ),
    ).toBe(true);
    expect(
      logs.some(
        (l) => l.level === 'info' && l.message === 'Setbuilder transport command received: unknown @ 0.0s',
      ),
    ).toBe(true);
  });
});
