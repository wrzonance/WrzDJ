import { beforeEach, describe, expect, it, vi } from 'vitest';
import { writeDebugReport } from '../debug-report-service.js';
import { DEFAULT_SETTINGS } from '../../shared/types.js';

const mocks = vi.hoisted(() => ({
  readFile: vi.fn(),
  writeFile: vi.fn(),
  mkdtemp: vi.fn(),
  rename: vi.fn(),
  rm: vi.fn(),
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

beforeEach(() => {
  vi.clearAllMocks();
  mocks.readFile.mockResolvedValue('current log');
  mocks.writeFile.mockResolvedValue(undefined);
  mocks.mkdtemp.mockResolvedValue('/tmp/.wrzdj-debug-report-unique');
  mocks.rename.mockResolvedValue(undefined);
  mocks.rm.mockResolvedValue(undefined);
});

describe('writeDebugReport', () => {
  it('writes a report with runtime, status, settings, and current logs', async () => {
    await writeDebugReport('/tmp/report.txt', {
      appVersion: '1.2.3',
      electronVersion: '44.0.0',
      nodeVersion: '24.0.0',
      chromeVersion: '140.0.0',
      os: 'Linux 6.0 (x64)',
      logPath: '/tmp/wrzdj.log',
      status: {
        isRunning: true,
        eventCode: 'EVENT1',
        connectedDevice: 'Deck 1',
        backendReachable: true,
        stopReason: null,
        currentTrack: { title: 'Track', artist: 'Artist', album: null, deckId: '1', startedAt: 1 },
        deckStates: [],
        networkWarnings: [],
      },
      settings: DEFAULT_SETTINGS,
    });

    expect(mocks.readFile).toHaveBeenCalledWith('/tmp/wrzdj.log', 'utf-8');
    expect(mocks.mkdtemp).toHaveBeenCalledWith('/tmp/.wrzdj-debug-report-');
    expect(mocks.writeFile).toHaveBeenCalledWith(
      '/tmp/.wrzdj-debug-report-unique/report.txt',
      expect.any(String),
      'utf-8',
    );
    expect(mocks.rename).toHaveBeenCalledWith(
      '/tmp/.wrzdj-debug-report-unique/report.txt',
      '/tmp/report.txt',
    );
    expect(mocks.rm).toHaveBeenCalledWith('/tmp/.wrzdj-debug-report-unique', {
      recursive: true,
      force: true,
    });
    const [, report] = mocks.writeFile.mock.calls[0];
    expect(report).toContain('App Version: 1.2.3');
    expect(report).toContain('Event Code: EVENT1');
    expect(report).toContain('Current Track: "Track" by Artist');
    expect(report).toContain('current log');
  });

  it('uses the rotated log when the current log is missing', async () => {
    mocks.readFile.mockRejectedValueOnce(Object.assign(new Error('missing'), { code: 'ENOENT' }));
    mocks.readFile.mockResolvedValueOnce('rotated log');

    await writeDebugReport('/tmp/report.txt', {
      appVersion: '1.2.3',
      electronVersion: '44.0.0',
      nodeVersion: '24.0.0',
      chromeVersion: '140.0.0',
      os: 'Linux 6.0 (x64)',
      logPath: '/tmp/wrzdj.log',
      status: {
        isRunning: false,
        eventCode: null,
        connectedDevice: null,
        backendReachable: false,
        stopReason: null,
        currentTrack: null,
        deckStates: [],
        networkWarnings: [],
      },
      settings: DEFAULT_SETTINGS,
    });

    expect(mocks.readFile).toHaveBeenNthCalledWith(2, '/tmp/wrzdj.log.1', 'utf-8');
    expect(mocks.writeFile.mock.calls[0][1]).toContain('rotated log');
  });

  it('surfaces primary log read failures other than a missing file', async () => {
    mocks.readFile.mockRejectedValueOnce(Object.assign(new Error('permission denied'), { code: 'EACCES' }));

    await expect(writeDebugReport('/tmp/report.txt', {
      appVersion: '1.2.3',
      electronVersion: '44.0.0',
      nodeVersion: '24.0.0',
      chromeVersion: '140.0.0',
      os: 'Linux 6.0 (x64)',
      logPath: '/tmp/wrzdj.log',
      status: {
        isRunning: false,
        eventCode: null,
        connectedDevice: null,
        backendReachable: false,
        stopReason: null,
        currentTrack: null,
        deckStates: [],
        networkWarnings: [],
      },
      settings: DEFAULT_SETTINGS,
    })).rejects.toThrow('permission denied');
    expect(mocks.writeFile).not.toHaveBeenCalled();
  });

  it('removes its private staging directory when publishing the report fails', async () => {
    const publishError = new Error('destination is unavailable');
    mocks.rename.mockRejectedValueOnce(publishError);

    await expect(writeDebugReport('/tmp/report.txt', {
      appVersion: '1.2.3',
      electronVersion: '44.0.0',
      nodeVersion: '24.0.0',
      chromeVersion: '140.0.0',
      os: 'Linux 6.0 (x64)',
      logPath: '/tmp/wrzdj.log',
      status: {
        isRunning: false,
        eventCode: null,
        connectedDevice: null,
        backendReachable: false,
        stopReason: null,
        currentTrack: null,
        deckStates: [],
        networkWarnings: [],
      },
      settings: DEFAULT_SETTINGS,
    })).rejects.toBe(publishError);

    expect(mocks.rm).toHaveBeenCalledWith('/tmp/.wrzdj-debug-report-unique', {
      recursive: true,
      force: true,
    });
  });
});
