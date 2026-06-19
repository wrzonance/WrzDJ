import { describe, it, expect, vi, beforeEach } from 'vitest';
import { checkEventHealth } from '../event-health-service.js';

const mockFetch = vi.fn();
global.fetch = mockFetch;

beforeEach(() => {
  vi.clearAllMocks();
});

describe('checkEventHealth', () => {
  it('returns "active" on 200 response', async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 200 });

    const result = await checkEventHealth('https://api.wrzdj.com', 'ABC123');

    expect(result).toBe('active');
    // Must hit the dual-resolver public event endpoint, which accepts EITHER the
    // collection code or the join_code. The bridge holds the collection code, and
    // the join-code-only /api/public/e/{code}/nowplaying would 404 on it — which
    // the health check would misread as 'not_found' and stop a live bridge.
    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.wrzdj.com/api/public/events/ABC123',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('returns "not_found" on 404 response', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 404 });

    const result = await checkEventHealth('https://api.wrzdj.com', 'GONE42');
    expect(result).toBe('not_found');
  });

  it('returns "expired" on 410 response', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 410 });

    const result = await checkEventHealth('https://api.wrzdj.com', 'OLD999');
    expect(result).toBe('expired');
  });

  it('returns "error" on 500 response', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 500 });

    const result = await checkEventHealth('https://api.wrzdj.com', 'ABC123');
    expect(result).toBe('error');
  });

  it('returns "error" on network failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'));

    const result = await checkEventHealth('https://api.wrzdj.com', 'ABC123');
    expect(result).toBe('error');
  });

  it('encodes the event code in the URL', async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 200 });

    await checkEventHealth('https://api.wrzdj.com', 'A B/C');

    expect(mockFetch).toHaveBeenCalledWith(
      'https://api.wrzdj.com/api/public/events/A%20B%2FC',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('passes an AbortSignal to fetch', async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 200 });

    await checkEventHealth('https://api.wrzdj.com', 'ABC123');

    const [, options] = mockFetch.mock.calls[0];
    expect(options).toBeDefined();
    expect(options.signal).toBeInstanceOf(AbortSignal);
  });

  it('returns "error" when fetch is aborted (timeout)', async () => {
    mockFetch.mockRejectedValue(new DOMException('The operation was aborted.', 'AbortError'));

    const result = await checkEventHealth('https://api.wrzdj.com', 'ABC123');
    expect(result).toBe('error');
  });
});
