'use client';

import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from 'react';
import { api } from './api';
import { initSeenPages } from './help/seen-pages';

export type UserRole = 'admin' | 'dj' | 'pending';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  role: UserRole | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

/**
 * The DJ session lives in an HttpOnly cookie set by the API (issue #754), so
 * this code never sees or stores the JWT. Because the cookie is invisible to
 * scripts, a non-secret marker records that a login happened on this browser;
 * it only decides whether to probe /api/auth/me on load, so guests and
 * logged-out visitors never make that request.
 */
export const SESSION_HINT_KEY = 'wrzdj_session_hint';
/** Pre-#754 builds persisted the raw JWT here; remove it wherever it still lingers. */
const LEGACY_TOKEN_KEY = 'token';

function readSessionHint(): boolean {
  try {
    return localStorage.getItem(SESSION_HINT_KEY) === '1';
  } catch {
    return false;
  }
}

function writeSessionHint(present: boolean): void {
  try {
    if (present) {
      localStorage.setItem(SESSION_HINT_KEY, '1');
    } else {
      localStorage.removeItem(SESSION_HINT_KEY);
    }
  } catch {
    // localStorage unavailable (privacy mode): the cookie still works, the probe just
    // will not run on the next load and the user logs in again.
  }
}

function dropLegacyToken(): void {
  try {
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    // localStorage unavailable
  }
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [role, setRole] = useState<UserRole | null>(null);

  const logout = useCallback(() => {
    writeSessionHint(false);
    api.setUnauthorizedHandler(null);
    setIsAuthenticated(false);
    setRole(null);
    // Best effort: clear the cookie server-side. Failure leaves an unusable cookie
    // behind at worst, which the next login overwrites.
    void api.endSession().catch(() => undefined);
  }, []);

  const redirectToLoginOnUnauthorized = useCallback(() => {
    api.setUnauthorizedHandler(() => {
      logout();
      window.location.href = '/login';
    });
  }, [logout]);

  useEffect(() => {
    dropLegacyToken();
    if (!readSessionHint()) {
      setIsLoading(false);
      return;
    }
    // No unauthorized handler during the probe: an expired cookie must not bounce a
    // visitor to /login, it just means "not signed in".
    api.getMe()
      .then((user) => {
        initSeenPages(user.help_pages_seen ?? []);
        redirectToLoginOnUnauthorized();
        setIsAuthenticated(true);
        setRole(user.role as UserRole);
      })
      .catch(() => {
        writeSessionHint(false);
      })
      .finally(() => setIsLoading(false));
  }, [redirectToLoginOnUnauthorized]);

  const login = async (username: string, password: string) => {
    // The response body also carries the token for bearer clients; it is
    // deliberately discarded here so it never touches script-readable storage.
    await api.login(username, password);
    writeSessionHint(true);
    redirectToLoginOnUnauthorized();
    const user = await api.getMe();
    initSeenPages(user.help_pages_seen ?? []);
    setRole(user.role as UserRole);
    setIsAuthenticated(true);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, role, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
