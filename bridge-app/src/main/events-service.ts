import type { EventInfo } from '../shared/types.js';

interface EventResponse {
  id: number;
  code: string;
  join_code: string;
  name: string;
  is_active: boolean;
  expires_at: string;
}

/**
 * Fetch the authenticated user's events from the backend.
 * Only returns active, non-expired events.
 */
export async function fetchEvents(
  apiUrl: string,
  token: string,
): Promise<readonly EventInfo[]> {
  const response = await fetch(`${apiUrl}/api/events`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('Session expired. Please log in again.');
    }
    const error = await response.json().catch(() => ({ detail: 'Failed to fetch events' }));
    throw new Error(error.detail || 'Failed to fetch events');
  }

  const events: EventResponse[] = await response.json();

  return events
    .filter((e) => e.is_active)
    .map((e) => ({
      id: e.id,
      code: e.code,
      joinCode: e.join_code,
      name: e.name,
      isActive: e.is_active,
      expiresAt: e.expires_at,
    }));
}
