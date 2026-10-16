import type { AuthState } from '../shared/types.js';

export interface LoginResult {
  readonly accessToken: string;
  readonly username: string;
}

/**
 * Authenticate against the WrzDJ backend.
 * Uses the same OAuth2 password flow as the dashboard.
 */
export async function login(
  apiUrl: string,
  username: string,
  password: string,
): Promise<LoginResult> {
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);

  const response = await fetch(`${apiUrl}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formData,
  });

  if (!response.ok) {
    const error: unknown = await response.json().catch(() => null);
    const detail = error !== null && typeof error === 'object' && 'detail' in error
      ? error.detail
      : undefined;
    throw new Error(typeof detail === 'string' && detail.trim() ? detail : 'Login failed');
  }

  const data: unknown = await response.json().catch(() => null);
  const accessToken =
    data !== null && typeof data === 'object' && 'access_token' in data
      ? data.access_token
      : undefined;
  if (typeof accessToken !== 'string' || accessToken.trim().length === 0) {
    throw new Error('Login response did not include a valid access token');
  }
  return { accessToken, username };
}

/**
 * Verify a stored token is still valid by calling /api/auth/me.
 * Returns the username if valid, null for definitive authorization failures.
 * Transport, server, and malformed-response failures are thrown so callers
 * can retain credentials during a transient outage.
 */
export async function verifyToken(
  apiUrl: string,
  token: string,
): Promise<string | null> {
  try {
    const response = await fetch(`${apiUrl}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (response.status === 401 || response.status === 403) {
      return null;
    }
    if (!response.ok) {
      throw new Error(`Token verification failed (${response.status})`);
    }
    const data: unknown = await response.json().catch((error: unknown) => {
      if (error instanceof SyntaxError) return null;
      throw error;
    });
    const username =
      data !== null && typeof data === 'object' && !Array.isArray(data) && 'username' in data
        ? data.username
        : undefined;
    if (typeof username !== 'string' || username.trim().length === 0) {
      throw new Error('Token verification returned an invalid username');
    }
    return username;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Token verification')) {
      throw error;
    }
    throw new Error('Token verification unavailable', { cause: error });
  }
}

/** Build an AuthState object */
export function buildAuthState(
  apiUrl: string,
  username: string | null,
): AuthState {
  return {
    isAuthenticated: username !== null,
    username,
    apiUrl,
  };
}
