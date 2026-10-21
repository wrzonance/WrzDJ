import { readBackendErrorDetail, readJsonBody, withErrorContext } from './backend-errors.js';

/**
 * Fetch the bridge API key from the backend using JWT auth.
 * The server returns the shared BRIDGE_API_KEY to authenticated users.
 */
export async function fetchBridgeApiKey(
  apiUrl: string,
  token: string,
): Promise<string> {
  const response = await withErrorContext('Bridge API key request failed', () => fetch(`${apiUrl}/api/bridge/apikey`, {
    headers: { Authorization: `Bearer ${token}` },
  }));

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('Session expired. Please log in again.');
    }
    if (response.status === 404) {
      throw new Error(
        'Bridge API key endpoint not found. Make sure the server is updated to the latest version.',
      );
    }
    if (response.status === 503) {
      throw new Error('Bridge API key not configured on server.');
    }
    const detail = await withErrorContext(
      'Bridge API key error response could not be read',
      () => readBackendErrorDetail(response, 'Failed to fetch bridge API key'),
    );
    throw new Error(detail);
  }

  const data = await withErrorContext(
    'Bridge API key response could not be read',
    () => readJsonBody(response),
  );
  if (
    data === null
    || typeof data !== 'object'
    || Array.isArray(data)
    || !('bridge_api_key' in data)
    || typeof data.bridge_api_key !== 'string'
    || data.bridge_api_key.trim().length === 0
  ) {
    throw new Error('Invalid bridge API key response');
  }
  return data.bridge_api_key;
}
