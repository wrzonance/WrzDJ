import type { EventInfo } from '../shared/types.js';
import { readBackendErrorDetail, readJsonBody, withErrorContext } from './backend-errors.js';

interface EventResponse {
  id: number;
  code: string;
  join_code: string;
  name: string;
  is_active: boolean;
  expires_at: string;
}

function isEventResponse(value: unknown): value is EventResponse {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const event = value as Record<string, unknown>;
  return Number.isSafeInteger(event.id)
    && typeof event.code === 'string'
    && typeof event.join_code === 'string'
    && typeof event.name === 'string'
    && typeof event.is_active === 'boolean'
    && typeof event.expires_at === 'string'
    && Number.isFinite(Date.parse(event.expires_at));
}

/**
 * Fetch the authenticated user's events from the backend.
 * Only returns active, non-expired events.
 */
export async function fetchEvents(
  apiUrl: string,
  token: string,
): Promise<readonly EventInfo[]> {
  const response = await withErrorContext('Event list request failed', () => fetch(`${apiUrl}/api/events`, {
    headers: { Authorization: `Bearer ${token}` },
  }));

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('Session expired. Please log in again.');
    }
    const detail = await withErrorContext(
      'Event list error response could not be read',
      () => readBackendErrorDetail(response, 'Failed to fetch events'),
    );
    throw new Error(detail);
  }

  const data = await withErrorContext(
    'Event list response could not be read',
    () => readJsonBody(response),
  );
  if (!Array.isArray(data) || !data.every(isEventResponse)) {
    throw new Error('Invalid events response');
  }
  const events = data;

  return events
    .filter((e) => e.is_active && Date.parse(e.expires_at) > Date.now())
    .map((e) => ({
      id: e.id,
      code: e.code,
      joinCode: e.join_code,
      name: e.name,
      isActive: e.is_active,
      expiresAt: e.expires_at,
    }));
}
