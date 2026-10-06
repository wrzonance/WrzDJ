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
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

const me = { id: 1, username: 'dj', role: 'dj', help_pages_seen: [] };

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
    expect(localStorage.getItem(SESSION_HINT_KEY)).toBe('1');
    expect(localStorage.getItem('token')).toBeNull();
    expect(Object.values({ ...localStorage })).not.toContain('secret-jwt');
    expect(mocks.setUnauthorizedHandler).toHaveBeenCalledWith(expect.any(Function));
  });

  it('logout drops the hint and ends the server session', async () => {
    localStorage.setItem(SESSION_HINT_KEY, '1');
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('in:dj'));
    await act(async () => {
      screen.getByText('logout').click();
    });
    expect(screen.getByTestId('state').textContent).toBe('out');
    expect(localStorage.getItem(SESSION_HINT_KEY)).toBeNull();
    expect(mocks.endSession).toHaveBeenCalledTimes(1);
    expect(mocks.setUnauthorizedHandler).toHaveBeenLastCalledWith(null);
  });

  it('removes a JWT persisted by a pre-#754 build', async () => {
    localStorage.setItem('token', 'old-secret-jwt');
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('out'));
    expect(localStorage.getItem('token')).toBeNull();
  });
});
