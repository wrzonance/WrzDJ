import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '..';

const fetchMock = vi.fn<typeof fetch>();

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('public API response transport', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    api.setKioskSession('kiosk-session');
  });

  afterEach(() => {
    api.setKioskSession(null);
    vi.unstubAllGlobals();
  });

  it('preserves structured error code and detail from event search responses', async () => {
    fetchMock.mockResolvedValueOnce(response({
      detail: { code: 'rate_limited', message: 'Slow down and retry.' },
    }, 429));

    await expect(api.eventSearch('EVT42', 'house')).rejects.toMatchObject({
      name: 'ApiError',
      status: 429,
      message: 'Slow down and retry.',
      code: 'rate_limited',
      detail: { code: 'rate_limited', message: 'Slow down and retry.' },
    });
  });

  it('keeps event search human verification retry and request credentials intact', async () => {
    const reverify = vi.fn(async () => {});
    fetchMock
      .mockResolvedValueOnce(response({
        detail: { code: 'human_verification_required', message: 'Verify first.' },
      }, 403))
      .mockResolvedValueOnce(response([{ title: 'Strobe', artist: 'deadmau5' }]));

    await expect(api.eventSearch('EVT42', 'deep house', reverify)).resolves.toEqual([
      { title: 'Strobe', artist: 'deadmau5' },
    ]);

    expect(reverify).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [url, init] of fetchMock.mock.calls) {
      expect(String(url)).toContain('/api/events/EVT42/search?q=deep%20house');
      expect(init?.credentials).toBe('include');
      expect(new Headers(init?.headers).get('X-Requested-With')).toBe('WrzDJ');
      expect(new Headers(init?.headers).get('X-Kiosk-Session')).toBe('kiosk-session');
    }
  });
});
