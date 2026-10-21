import type { AuthState } from '../shared/types.js';
import { readBackendErrorDetail, readJsonBody, withErrorContext } from './backend-errors.js';

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

  const response = await withErrorContext('Login request failed', () => fetch(`${apiUrl}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formData,
  }));

  if (!response.ok) {
    const detail = await withErrorContext(
      'Login error response could not be read',
      () => readBackendErrorDetail(response, 'Login failed'),
    );
    throw new Error(detail);
  }

  const data = await withErrorContext(
    'Login response could not be read',
    () => readJsonBody(response),
  );
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
  const response = await withErrorContext('Token verification unavailable', () => fetch(
    `${apiUrl}/api/auth/me`,
    { headers: { Authorization: `Bearer ${token}` } },
  ));

  if (response.status === 401 || response.status === 403) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Token verification failed (${response.status})`);
  }

  const data = await withErrorContext(
    'Token verification unavailable',
    () => readJsonBody(response),
  );
  const username =
    data !== null && typeof data === 'object' && !Array.isArray(data) && 'username' in data
      ? data.username
      : undefined;
  if (typeof username !== 'string' || username.trim().length === 0) {
    throw new Error('Token verification returned an invalid username');
  }
  return username;
}

/** Build an AuthState object */
export function buildAuthState(
  apiUrl: string,
  username: string | null,
  verificationError: string | null = null,
): AuthState {
  return {
    isAuthenticated: username !== null,
    username,
    apiUrl,
    verificationError,
  };
}
