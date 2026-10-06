/**
 * AuthProvider after issue #754: the JWT lives in an HttpOnly cookie, so the
 * provider must never read or write a token, must only probe /me when a
 * session hint exists, and must end the server session on logout.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  getMe: vi.fn(),
  endSession: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}));

vi.mock('../api', () => ({ api: mocks }));
vi.mock('../help/seen-pages', () => ({ initSeenPages: vi.fn() }));

import { AuthProvider, SESSION_HINT_KEY, useAuth } from '../auth';

function Probe() {
  const { isAuthenticated, isLoading, role, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="state">
        {isLoading ? 'loading' : isAuthenticated ? `in:${role}` : 'out'}
      </span>
      <button onClick={() => void login('dj', 'pw')}>login</button>
      <button onClick={() => void logout()}>logout</button>
    </div>
  );
}

const me = { id: 1, username: 'dj', role: 'dj', help_pages_seen: [] };

/** Simulate another tab writing localStorage (jsdom never fires `storage` on its own). */
function fireStorage(key: string, oldValue: string | null, newValue: string | null) {
  const event = Object.assign(new Event('storage'), { key, oldValue, newValue });
  window.dispatchEvent(event);
}

describe('AuthProvider (cookie session)', () => {
  beforeEach(() => {
    localStorage.clear();
    mocks.login.mockReset().mockResolvedValue({ access_token: 'secret-jwt' });
    mocks.getMe.mockReset().mockResolvedValue(me);
    mocks.endSession.mockReset().mockResolvedValue(undefined);
    mocks.setUnauthorizedHandler.mockReset();
  });

  it('does not probe /me when no session hint is present', async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('out'));
    expect(mocks.getMe).not.toHaveBeenCalled();
  });

  it('restores the session from the cookie when the hint is present', async () => {
    localStorage.setItem(SESSION_HINT_KEY, '1');
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('in:dj'));
    expect(mocks.getMe).toHaveBeenCalledTimes(1);
  });

  it('clears the hint, without redirecting, when the cookie no longer authenticates', async () => {
    localStorage.setItem(SESSION_HINT_KEY, '1');
    mocks.getMe.mockRejectedValue(new Error('401'));
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('out'));
    expect(localStorage.getItem(SESSION_HINT_KEY)).toBeNull();
    // The redirect handler is only installed once a probe succeeds.
    expect(mocks.setUnauthorizedHandler).not.toHaveBeenCalled();
  });

  it('never stores the JWT; login leaves only the hint in localStorage', async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('out'));
    await act(async () => {
      screen.getByText('login').click();
    });
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('in:dj'));
    expect(localStorage.getItem(SESSION_HINT_KEY)).toBeTruthy();
    expect(localStorage.getItem('token')).toBeNull();
    expect(Object.values({ ...localStorage })).not.toContain('secret-jwt');
    expect(mocks.setUnauthorizedHandler).toHaveBeenCalledWith(expect.any(Function));
  });

  it('logout asks the server to end the session before reporting logged-out', async () => {
    localStorage.setItem(SESSION_HINT_KEY, '1');
    let finishDelete: () => void = () => undefined;
    mocks.endSession.mockReturnValue(new Promise<void>((resolve) => { finishDelete = resolve; }));
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('in:dj'));
    await act(async () => {
      screen.getByText('logout').click();
    });
    // DELETE still in flight: hint already dropped, UI still signed in.
    expect(mocks.endSession).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(SESSION_HINT_KEY)).toBeNull();
    expect(screen.getByTestId('state').textContent).toBe('in:dj');
    await act(async () => {
      finishDelete();
    });
    expect(screen.getByTestId('state').textContent).toBe('out');
    expect(mocks.setUnauthorizedHandler).toHaveBeenLastCalledWith(null);
  });

  it('logout still clears local state when the server cannot be reached', async () => {
    localStorage.setItem(SESSION_HINT_KEY, '1');
    mocks.endSession.mockRejectedValue(new Error('network'));
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('in:dj'));
    await act(async () => {
      screen.getByText('logout').click();
    });
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('out'));
    expect(localStorage.getItem(SESSION_HINT_KEY)).toBeNull();
  });

  it('each login writes a new session generation so other tabs can tell logins apart', async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('out'));
    await act(async () => { screen.getByText('login').click(); });
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('in:dj'));
    const first = localStorage.getItem(SESSION_HINT_KEY);
    await act(async () => { screen.getByText('login').click(); });
    await waitFor(() => expect(mocks.login).toHaveBeenCalledTimes(2));
    const second = localStorage.getItem(SESSION_HINT_KEY);
    expect(first).toBeTruthy();
    expect(second).toBeTruthy();
    expect(second).not.toBe(first);
  });

  it('reloads when another tab changes the session', async () => {
    const reload = vi.fn();
    const original = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...original, reload },
    });
    try {
      render(<AuthProvider><Probe /></AuthProvider>);
      await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('out'));
      act(() => {
        fireStorage(SESSION_HINT_KEY, null, 'abc-123');
      });
      expect(reload).toHaveBeenCalledTimes(1);
      // Unrelated keys and no-op writes are ignored.
      act(() => {
        fireStorage('wrzdj-theme', 'a', 'b');
        fireStorage(SESSION_HINT_KEY, 'x', 'x');
      });
      expect(reload).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original });
    }
  });

  it('removes a JWT persisted by a pre-#754 build', async () => {
    localStorage.setItem('token', 'old-secret-jwt');
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('out'));
    expect(localStorage.getItem('token')).toBeNull();
  });
});
