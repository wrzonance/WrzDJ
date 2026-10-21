import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchEvents } from '../events-service.js';

const mockFetch = vi.fn();
global.fetch = mockFetch;

beforeEach(() => {
  vi.clearAllMocks();
});

describe('fetchEvents', () => {
  it('fetches and transforms active events that have not expired', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([
        { id: 1, code: 'ABC123', join_code: 'JOIN01', name: 'Live Set', is_active: true, expires_at: '2026-12-31T00:00:00Z' },
        { id: 2, code: 'DEF456', join_code: 'JOIN02', name: 'Expired Event', is_active: false, expires_at: '2025-01-01T00:00:00Z' },
        { id: 3, code: 'GHI789', join_code: 'JOIN03', name: 'Another Set', is_active: true, expires_at: '2026-12-31T00:00:00Z' },
        { id: 4, code: 'JKL012', join_code: 'JOIN04', name: 'Expired Active Event', is_active: true, expires_at: '2000-01-01T00:00:00Z' },
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

  // Regression for 57cfcdc6867f: backend transport errors include operation context and cause.
  it('adds event-list context and preserves the original fetch failure', async () => {
    const failure = new TypeError('network disconnected');
    mockFetch.mockRejectedValue(failure);

    await expect(fetchEvents('https://api.wrzdj.com', 'token')).rejects.toMatchObject({
      message: 'Event list request failed',
      cause: failure,
    });
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

  it.each([42, {}, '   '])('uses a safe fallback for malformed error detail %j', async (detail) => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail }),
    });

    await expect(fetchEvents('https://api.wrzdj.com', 'token'))
      .rejects.toThrow('Failed to fetch events');
  });

  it('returns empty array when no events exist', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });

    const events = await fetchEvents('https://api.wrzdj.com', 'token');
    expect(events).toEqual([]);
  });

  it('rejects malformed event rows instead of returning values that violate EventInfo', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([
        { id: '1', code: 'ABC123', join_code: 'JOIN01', name: 'Live Set', is_active: true, expires_at: '2026-12-31T00:00:00Z' },
      ]),
    });

    await expect(fetchEvents('https://api.wrzdj.com', 'token'))
      .rejects.toThrow('Invalid events response');
  });

  it('adds event-list context to successful-response body stream failures', async () => {
    const failure = new TypeError('body stream terminated');
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.reject(failure) });

    await expect(fetchEvents('https://api.wrzdj.com', 'token')).rejects.toMatchObject({
      message: 'Event list response could not be read',
      cause: failure,
    });
  });

  it('adds event-list context to error-response body stream failures', async () => {
    const failure = new TypeError('error response body terminated');
    mockFetch.mockResolvedValue({ ok: false, status: 500, json: () => Promise.reject(failure) });

    await expect(fetchEvents('https://api.wrzdj.com', 'token')).rejects.toMatchObject({
      message: 'Event list error response could not be read',
      cause: failure,
    });
  });

  it('rejects event rows with an unparseable expiration timestamp', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([
        { id: 1, code: 'ABC123', join_code: 'JOIN01', name: 'Live Set', is_active: true, expires_at: 'not-a-date' },
      ]),
    });

    await expect(fetchEvents('https://api.wrzdj.com', 'token'))
      .rejects.toThrow('Invalid events response');
  });

  it('rejects a non-array events response', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ events: [] }) });

    await expect(fetchEvents('https://api.wrzdj.com', 'token'))
      .rejects.toThrow('Invalid events response');
  });
});
