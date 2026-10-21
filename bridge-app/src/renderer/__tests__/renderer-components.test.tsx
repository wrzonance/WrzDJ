import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BridgeSettings, BridgeStatus, EventInfo, PluginMeta } from '../../shared/types.js';

const mocks = vi.hoisted(() => ({
  api: {
    getAuthState: vi.fn(), onAuthChanged: vi.fn(), login: vi.fn(), logout: vi.fn(),
    fetchEvents: vi.fn(), onBridgeStatus: vi.fn(), onBridgeLog: vi.fn(), onPing: vi.fn(),
    getSettings: vi.fn(), updateSettings: vi.fn(), listPluginMeta: vi.fn(), exportDebugReport: vi.fn(),
  },
}));

vi.mock('../api.js', () => ({ api: mocks.api }));

import { App } from '../App.js';
import { LoginForm } from '../components/LoginForm.js';
import { LogPanel } from '../components/LogPanel.js';
import { SettingsPanel } from '../components/SettingsPanel.js';
import { StatusPanel } from '../components/StatusPanel.js';
import { useBridgeLog } from '../hooks/useBridgeLog.js';
import { useBridgeStatus } from '../hooks/useBridgeStatus.js';
import type { LogEntry } from '../hooks/useBridgeLog.js';

const status: BridgeStatus = {
  isRunning: true, connectedDevice: 'Player 1', eventCode: 'EVENT1', eventName: null,
  currentTrack: { title: 'Track', artist: 'Artist', album: 'Album', deckId: '1', startedAt: 0 },
  deckStates: [{ deckId: '1', state: 'PLAYING', trackTitle: 'Track', trackArtist: 'Artist', isPlaying: true, isMaster: true, faderLevel: 1 }],
  backendReachable: false, stopReason: null, networkWarnings: ['Subnet conflict'],
  circuitBreakerState: 'CLOSED', bufferSize: 0, deckCount: 1, uptimeSeconds: 12, pluginId: 'test',
};

const defaultSettings: BridgeSettings = {
  protocol: 'test', liveThresholdSeconds: 15, pauseGraceSeconds: 3,
  nowPlayingPauseSeconds: 10, minPlaySeconds: 5, useFaderDetection: false,
  masterDeckPriority: false, pluginConfig: {},
};

const plugin: PluginMeta = {
  info: { id: 'test', name: 'Test Protocol', description: 'Test' },
  capabilities: { multiDeck: true, playState: true, faderLevel: false, masterDeck: false, albumMetadata: true },
  configOptions: [
    { key: 'library', label: 'Library name', type: 'string', default: 'Main' },
    { key: 'gain', label: 'Gain', type: 'number', default: 8 },
    { key: 'enabled', label: 'Enabled', type: 'boolean', default: false },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.api.getAuthState.mockResolvedValue({ isAuthenticated: false, username: null, apiUrl: 'https://api.example.test', verificationError: null });
  mocks.api.onAuthChanged.mockReturnValue(vi.fn());
  mocks.api.onBridgeStatus.mockReturnValue(vi.fn());
  mocks.api.onBridgeLog.mockReturnValue(vi.fn());
  mocks.api.onPing.mockReturnValue(vi.fn());
  mocks.api.fetchEvents.mockResolvedValue([] as EventInfo[]);
  mocks.api.getSettings.mockResolvedValue(defaultSettings);
  mocks.api.listPluginMeta.mockResolvedValue([plugin]);
  mocks.api.updateSettings.mockImplementation(async (partial: Partial<BridgeSettings>) => ({ ...defaultSettings, ...partial }));
  mocks.api.exportDebugReport.mockResolvedValue('/tmp/wrzdj-debug.txt');
  Object.defineProperty(window, 'bridgeApi', { configurable: true, value: { onPing: vi.fn(() => vi.fn()) } });
});

describe('renderer app and status display', () => {
  it('shows loading before switching to the unauthenticated sign-in flow', async () => {
    render(<App />);
    expect(screen.getByText('Loading...')).toBeTruthy();
    await waitFor(() => expect(screen.getByLabelText('Server URL')).toBeTruthy());
  });

  it('renders live connection, selected join code, warnings, track, and deck state', () => {
    render(<StatusPanel status={status} joinCode="JOIN1" />);

    expect(screen.getByText('JOIN1')).toBeTruthy();
    expect(screen.getByText('Player 1')).toBeTruthy();
    expect(screen.getByText('Backend unreachable — track updates are not being sent.')).toBeTruthy();
    expect(screen.getByText('Subnet conflict')).toBeTruthy();
    expect(screen.getByText(/Album/)).toBeTruthy();
    expect(screen.getByText('PLAYING')).toBeTruthy();
  });

  it('submits sign-in values and displays the parent error', async () => {
    const onLogin = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<LoginForm onLogin={onLogin} error={null} loading={false} />);
    fireEvent.change(screen.getByLabelText('Server URL'), { target: { value: 'https://custom.example' } });
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'dj' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith('https://custom.example', 'dj', 'secret'));
    rerender(<LoginForm onLogin={onLogin} error="Bad credentials" loading={true} />);
    expect(screen.getByText('Bad credentials')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Signing in...' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('settings and diagnostics panels', () => {
  it('loads settings and plugin options and persists edits', async () => {
    render(<SettingsPanel />);
    fireEvent.click(screen.getByText('Detection Settings'));
    const threshold = await screen.findByDisplayValue('15');
    fireEvent.change(threshold, { target: { value: '22' } });
    await waitFor(() => expect(mocks.api.updateSettings).toHaveBeenCalledWith({ liveThresholdSeconds: 22 }));

    const library = await screen.findByDisplayValue('Main');
    fireEvent.change(library, { target: { value: 'Performance' } });
    await waitFor(() => expect(mocks.api.updateSettings).toHaveBeenCalledWith({ pluginConfig: { library: 'Performance' } }));
  });

  it('uses plugin defaults when stored values have mismatched runtime types', async () => {
    mocks.api.getSettings.mockResolvedValueOnce({
      ...defaultSettings,
      pluginConfig: { library: 42, gain: 'loud', enabled: 'yes' },
    });
    render(<SettingsPanel />);
    fireEvent.click(screen.getByText('Detection Settings'));

    expect(await screen.findByDisplayValue('Main')).toBeTruthy();
    expect(await screen.findByDisplayValue('8')).toBeTruthy();
    const enabledToggle = (await screen.findByText('Enabled')).parentElement?.querySelector('button');
    expect(enabledToggle).not.toBeNull();
    expect(enabledToggle?.className).not.toContain('active');
  });

  it('preserves zero for a numeric plugin option whose metadata permits zero', async () => {
    mocks.api.listPluginMeta.mockResolvedValueOnce([{
      ...plugin,
      configOptions: plugin.configOptions.map((option) => option.key === 'gain'
        ? { ...option, default: 7, min: 0 }
        : option),
    }]);
    render(<SettingsPanel />);
    fireEvent.click(screen.getByText('Detection Settings'));
    const gain = await screen.findByDisplayValue('7');

    fireEvent.change(gain, { target: { value: '0' } });

    await waitFor(() => expect(mocks.api.updateSettings).toHaveBeenCalledWith({
      pluginConfig: { gain: 0 },
    }));
  });

  it('locks protocol and plugin-specific controls while the bridge is running', async () => {
    mocks.api.onBridgeStatus.mockImplementation((callback) => {
      callback(status);
      return vi.fn();
    });
    render(<SettingsPanel />);
    fireEvent.click(screen.getByText('Detection Settings'));

    expect((await screen.findByRole('combobox') as HTMLSelectElement).disabled).toBe(true);
    expect((await screen.findByDisplayValue('Main') as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText('Stop the bridge to change protocol.')).toBeTruthy();
  });

  it('exports diagnostics and clears visible log entries', async () => {
    const onClear = vi.fn();
    const entries: LogEntry[] = [{ id: 1, timestamp: 0, message: 'Bridge ready', level: 'info' }];
    render(<LogPanel entries={entries} onClear={onClear} />);
    fireEvent.click(screen.getByText('Diagnostic Log'));
    expect(screen.getByText('Bridge ready')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Export Report' }));
    await waitFor(() => expect(screen.getByText('Report saved')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(onClear).toHaveBeenCalledOnce();
  });

  it('shows the debug report export failure reason with a safe fallback', async () => {
    mocks.api.exportDebugReport.mockRejectedValueOnce(new Error('disk is full'));
    render(<LogPanel entries={[]} onClear={vi.fn()} />);
    fireEvent.click(screen.getByText('Diagnostic Log'));
    fireEvent.click(screen.getByRole('button', { name: 'Export Report' }));

    await waitFor(() => expect(screen.getByText('Export failed: disk is full')).toBeTruthy());
  });

  it('uses a safe debug report failure message for non-Error rejections', async () => {
    mocks.api.exportDebugReport.mockRejectedValueOnce('unexpected failure');
    render(<LogPanel entries={[]} onClear={vi.fn()} />);
    fireEvent.click(screen.getByText('Diagnostic Log'));
    fireEvent.click(screen.getByRole('button', { name: 'Export Report' }));

    await waitFor(() => expect(screen.getByText('Export failed')).toBeTruthy());
  });

  it('styles log levels and messages with severity classes', () => {
    const entries: LogEntry[] = [
      { id: 1, timestamp: 0, message: 'warning', level: 'warn' },
      { id: 2, timestamp: 1, message: 'failure', level: 'error' },
    ];
    render(<LogPanel entries={entries} onClear={vi.fn()} />);
    fireEvent.click(screen.getByText('Diagnostic Log'));

    expect(screen.getByText('WRN').className).toContain('log-level-warn');
    expect(screen.getByText('warning').className).toContain('log-message-warn');
    expect(screen.getByText('ERR').className).toContain('log-level-error');
    expect(screen.getByText('failure').className).toContain('log-message-error');
  });
});

describe('renderer event hooks', () => {
  it('updates status from bridge events and unsubscribes on unmount', () => {
    let receiveStatus: ((next: BridgeStatus) => void) | undefined;
    const unsubscribe = vi.fn();
    mocks.api.onBridgeStatus.mockImplementation((callback) => { receiveStatus = callback; return unsubscribe; });
    const { result, unmount } = renderHook(() => useBridgeStatus());
    expect(result.current.isRunning).toBe(false);
    act(() => receiveStatus?.(status));
    expect(result.current).toEqual(status);
    unmount();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it('appends logs, clears them, and unsubscribes on unmount', () => {
    let receiveLog: ((entry: { message: string; level: LogEntry['level'] }) => void) | undefined;
    const unsubscribe = vi.fn();
    mocks.api.onBridgeLog.mockImplementation((callback) => { receiveLog = callback; return unsubscribe; });
    const { result, unmount } = renderHook(() => useBridgeLog());
    act(() => receiveLog?.({ message: 'Connected', level: 'info' }));
    expect(result.current.entries).toHaveLength(1);
    expect(result.current.entries[0]).toMatchObject({ message: 'Connected', level: 'info' });
    act(() => result.current.clear());
    expect(result.current.entries).toEqual([]);
    unmount();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });
});
