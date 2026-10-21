import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAuth } from '../hooks/useAuth.js';
import { EventSelector } from '../components/EventSelector.js';
import { BridgeControls } from '../components/BridgeControls.js';
import type { AuthState, BridgeStatus, EventInfo } from '../../shared/types.js';

const mocks = vi.hoisted(() => ({
  getAuthState: vi.fn(),
  onAuthChanged: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  fetchEvents: vi.fn(),
  startBridge: vi.fn(),
  stopBridge: vi.fn(),
}));

vi.mock('../api.js', () => ({ api: mocks }));

const authenticated: AuthState = {
  isAuthenticated: true,
  username: 'dj',
  apiUrl: 'https://api.example.test',
  verificationError: null,
};

const event: EventInfo = {
  id: 1,
  code: 'EVENT1',
  joinCode: 'JOIN1',
  name: 'Saturday Set',
  isActive: true,
  expiresAt: '2026-12-31T00:00:00Z',
};

const status: BridgeStatus = {
  isRunning: false,
  connectedDevice: null,
  eventCode: null,
  eventName: null,
  currentTrack: null,
  deckStates: [],
  stopReason: null,
  backendReachable: true,
  networkWarnings: [],
  circuitBreakerState: 'CLOSED',
  bufferSize: 0,
  deckCount: 0,
  uptimeSeconds: 0,
  pluginId: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getAuthState.mockResolvedValue(authenticated);
  mocks.onAuthChanged.mockReturnValue(vi.fn());
  mocks.login.mockResolvedValue(undefined);
  mocks.logout.mockResolvedValue(undefined);
  mocks.fetchEvents.mockResolvedValue([event]);
  mocks.startBridge.mockResolvedValue(undefined);
  mocks.stopBridge.mockResolvedValue(undefined);
});

describe('renderer auth workflow', () => {
  it('loads stored auth state and subscribes to auth changes', async () => {
    const { result } = renderHook(() => useAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.authState).toEqual(authenticated);
    expect(mocks.onAuthChanged).toHaveBeenCalledOnce();
  });

  it('reports login errors while restoring the non-loading state', async () => {
    mocks.login.mockRejectedValueOnce(new Error('Bad credentials'));
    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await expect(result.current.login('https://api.example.test', 'dj', 'wrong'))
        .rejects.toThrow('Bad credentials');
    });

    expect(result.current.error).toBe('Bad credentials');
    expect(result.current.loading).toBe(false);
  });

  it('shows a saved-session verification outage without clearing the auth state error', async () => {
    mocks.getAuthState.mockResolvedValueOnce({
      isAuthenticated: false,
      username: null,
      apiUrl: 'https://api.example.test',
      verificationError: 'Could not verify the saved session. Check the connection and try again.',
    });
    const { result } = renderHook(() => useAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error)
      .toBe('Could not verify the saved session. Check the connection and try again.');
  });

  it('reports an initial auth-state IPC failure instead of presenting confirmed logout', async () => {
    mocks.getAuthState.mockRejectedValueOnce(new Error('IPC unavailable'));
    const { result } = renderHook(() => useAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.authState).toMatchObject({ isAuthenticated: false, username: null });
    expect(result.current.error).toBe('Could not load saved authentication state. Please try again.');
  });

  it('keeps a newer auth event when the initial saved-state lookup completes late', async () => {
    // Regression for 57cfcdc6867f: an old get-state response must not overwrite a newer login event.
    let finishLookup!: (state: AuthState) => void;
    let receiveAuthChange: ((state: AuthState) => void) | undefined;
    mocks.getAuthState.mockImplementationOnce(() => new Promise((resolve) => {
      finishLookup = resolve;
    }));
    mocks.onAuthChanged.mockImplementationOnce((listener) => {
      receiveAuthChange = listener;
      return vi.fn();
    });
    const { result } = renderHook(() => useAuth());

    act(() => receiveAuthChange?.(authenticated));
    await act(async () => {
      finishLookup({
        isAuthenticated: false,
        username: null,
        apiUrl: 'https://api.example.test',
        verificationError: null,
      });
    });

    expect(result.current.authState).toEqual(authenticated);
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });
});

describe('event selection workflow', () => {
  it('loads events and returns the selected event to its parent', async () => {
    const onSelect = vi.fn();
    render(<EventSelector selectedCode={null} onSelect={onSelect} />);

    fireEvent.click(await screen.findByText('JOIN1'));

    expect(onSelect).toHaveBeenCalledWith(event);
  });

  it('clears a selection when a refresh no longer returns that event', async () => {
    const onEventRemoved = vi.fn();
    render(<EventSelector selectedCode="REMOVED" onSelect={vi.fn()} onEventRemoved={onEventRemoved} />);

    await waitFor(() => expect(onEventRemoved).toHaveBeenCalledWith('REMOVED'));
  });

  it('clears a foreground load error when a background refresh recovers', async () => {
    // Regression for baseline 57cfcdc6867f: a recovered background refresh must clear the stale error view.
    vi.useFakeTimers();
    try {
      mocks.fetchEvents.mockRejectedValueOnce(new Error('Temporary event-list outage'));
      render(<EventSelector selectedCode={null} onSelect={vi.fn()} />);
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByText('Temporary event-list outage')).toBeTruthy();

      mocks.fetchEvents.mockResolvedValueOnce([event]);
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });

      expect(screen.getByText('Saturday Set')).toBeTruthy();
      expect(screen.queryByText('Temporary event-list outage')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('ignores an older refresh that completes after a newer result', async () => {
    vi.useFakeTimers();
    let resolveInitial!: (value: readonly EventInfo[]) => void;
    let resolveRefresh!: (value: readonly EventInfo[]) => void;
    mocks.fetchEvents
      .mockImplementationOnce(() => new Promise((resolve) => { resolveInitial = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve; }));
    const onEventRemoved = vi.fn();
    try {
      render(<EventSelector selectedCode="EVENT1" onSelect={vi.fn()} onEventRemoved={onEventRemoved} />);
      await act(async () => { await Promise.resolve(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
      expect(mocks.fetchEvents).toHaveBeenCalledTimes(2);

      await act(async () => { resolveRefresh([event]); });
      await act(async () => { resolveInitial([]); });

      expect(screen.getByText('JOIN1')).toBeTruthy();
      expect(onEventRemoved).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('bridge control workflow', () => {
  it('starts for the selected event and disables start without a selection', async () => {
    const { rerender } = render(
      <BridgeControls status={status} selectedEventCode={null} joinCode={null} />,
    );
    expect((screen.getByRole('button', { name: 'Start Bridge' }) as HTMLButtonElement).disabled).toBe(true);

    rerender(<BridgeControls status={status} selectedEventCode="EVENT1" joinCode="JOIN1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Start Bridge' }));
    await waitFor(() => expect(mocks.startBridge).toHaveBeenCalledWith('EVENT1'));
  });

  it('stops a running bridge and displays the live join code', async () => {
    render(
      <BridgeControls
        status={{ ...status, isRunning: true, eventCode: 'EVENT1' }}
        selectedEventCode={null}
        joinCode="JOIN1"
      />,
    );

    expect(screen.getByText(/Running for event/).textContent).toContain('JOIN1');
    fireEvent.click(screen.getByRole('button', { name: 'Stop Bridge' }));
    await waitFor(() => expect(mocks.stopBridge).toHaveBeenCalledOnce());
  });
});
