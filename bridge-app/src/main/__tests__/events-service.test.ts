import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchEvents } from '../events-service.js';

const mockFetch = vi.fn();
global.fetch = mockFetch;

beforeEach(() => {
  vi.clearAllMocks();
});

describe('fetchEvents', () => {
  it('fetches and transforms events, filtering to active only', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([
        { id: 1, code: 'ABC123', join_code: 'JOIN01', name: 'Live Set', is_active: true, expires_at: '2026-12-31T00:00:00Z' },
        { id: 2, code: 'DEF456', join_code: 'JOIN02', name: 'Expired Event', is_active: false, expires_at: '2025-01-01T00:00:00Z' },
        { id: 3, code: 'GHI789', join_code: 'JOIN03', name: 'Another Set', is_active: true, expires_at: '2026-12-31T00:00:00Z' },
      ]),
    });

    const events = await fetchEvents('https://api.wrzdj.com', 'token-123');

    // The bridge must surface join_code (the code guests use / shown in the
    // dashboard), not just the internal collection code.
    expect(events).toEqual([
      { id: 1, code: 'ABC123', joinCode: 'JOIN01', name: 'Live Set', isActive: true, expiresAt: '2026-12-31T00:00:00Z' },
      { id: 3, code: 'GHI789', joinCode: 'JOIN03', name: 'Another Set', isActive: true, expiresAt: '2026-12-31T00:00:00Z' },
    ]);

    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.wrzdj.com/api/events',
      { headers: { Authorization: 'Bearer token-123' } },
    );
  });

  it('throws on 401 with session expired message', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: 'Unauthorized' }),
    });

    await expect(fetchEvents('https://api.wrzdj.com', 'bad-token'))
      .rejects.toThrow('Session expired');
  });

  it('throws with detail on other errors', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail: 'Internal server error' }),
    });

    await expect(fetchEvents('https://api.wrzdj.com', 'token'))
      .rejects.toThrow('Internal server error');
  });

  it('returns empty array when no events exist', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });

    const events = await fetchEvents('https://api.wrzdj.com', 'token');
    expect(events).toEqual([]);
  });
});
