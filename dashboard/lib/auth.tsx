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
  /** Resolves once the server has been asked to end the session (see logout notes). */
  logout: () => Promise<void>;
}

/**
 * The DJ session lives in an HttpOnly cookie set by the API (issue #754), so
 * this code never sees or stores the JWT. Because the cookie is invisible to
 * scripts, a non-secret marker records that a login happened on this browser.
 * It decides whether to probe /api/auth/me on load, so guests and logged-out
 * visitors never make that request, and its value changes on every login and
 * logout so other tabs notice (cookies are shared across tabs, React state is
 * not) and reload instead of silently acting as a different account.
 */
export const SESSION_HINT_KEY = 'wrzdj_session_hint';
/** Pre-#754 builds persisted the raw JWT here; remove it wherever it still lingers. */
const LEGACY_TOKEN_KEY = 'token';

function readSessionHint(): string | null {
  try {
    return localStorage.getItem(SESSION_HINT_KEY);
  } catch {
    return null;
  }
}

/** A fresh, non-secret generation marker; distinct per login so cross-tab change is visible. */
function newSessionGeneration(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function writeSessionHint(value: string | null): void {
  try {
    if (value) {
      localStorage.setItem(SESSION_HINT_KEY, value);
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

  const logout = useCallback(async () => {
    writeSessionHint(null);
    api.setUnauthorizedHandler(null);
    try {
      // Ask the server to delete the cookie BEFORE reporting logged-out, so a
      // navigation that follows cannot cancel the request.
      await api.endSession();
    } catch {
      // The server could not be reached. The cookie then stays in the browser
      // until it expires; nothing in this app will send it again because the
      // hint is gone, but a shared machine is not fully signed out until expiry.
    }
    setIsAuthenticated(false);
    setRole(null);
  }, []);

  const redirectToLoginOnUnauthorized = useCallback(() => {
    api.setUnauthorizedHandler(() => {
      void logout().finally(() => {
        window.location.href = '/login';
      });
    });
  }, [logout]);

  // Initial restore: probe /me only when this browser recorded a login.
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
        writeSessionHint(null);
      })
      .finally(() => setIsLoading(false));
  }, [redirectToLoginOnUnauthorized]);

  // Cross-tab sync: another tab logged in or out, so the shared cookie now
  // belongs to a different (or no) account. Reload rather than keep showing
  // this tab's stale principal and account-specific state.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === SESSION_HINT_KEY && event.newValue !== event.oldValue) {
        window.location.reload();
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const login = async (username: string, password: string) => {
    // The response body also carries the token for bearer clients; it is
    // deliberately discarded here so it never touches script-readable storage.
    await api.login(username, password);
    writeSessionHint(newSessionGeneration());
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
