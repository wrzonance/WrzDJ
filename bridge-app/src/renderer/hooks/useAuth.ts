import { useState, useEffect, useCallback } from 'react';
import { api } from '../api.js';
import type { AuthState } from '../../shared/types.js';

const INITIAL_STATE: AuthState = {
  isAuthenticated: false,
  username: null,
  apiUrl: 'https://api.wrzdj.com',
  verificationError: null,
};

export function useAuth() {
  const [authState, setAuthState] = useState<AuthState>(INITIAL_STATE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    let authChangedDuringLoad = false;

    // Subscribe first so an auth change cannot land between the snapshot request and subscription.
    const unsubscribe = api.onAuthChanged((state) => {
      authChangedDuringLoad = true;
      setAuthState(state);
      setError(null);
      setLoading(false);
    });

    // Check stored auth on mount; discard the snapshot if a newer auth event arrived meanwhile.
    api.getAuthState().then((state) => {
      if (disposed || authChangedDuringLoad) return;
      setAuthState(state);
      setError(state.verificationError);
      setLoading(false);
    }).catch(() => {
      if (disposed || authChangedDuringLoad) return;
      setError('Could not load saved authentication state. Please try again.');
      setLoading(false);
    });

    return () => {
      disposed = true;
      unsubscribe();
    };
  }, []);

  const login = useCallback(async (apiUrl: string, username: string, password: string) => {
    setError(null);
    setLoading(true);
    try {
      await api.login(apiUrl, username, password);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed';
      setError(message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => api.logout(), []);

  return { authState, loading, error, login, logout };
}
