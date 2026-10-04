import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';

// Regression for #730, present at 58dc3dd15d2a96a79c5422e1c805d5d80aafdb1b.
// Exercise the real Thumbmark package; only browser/network boundaries are stubbed.
describe('guest fingerprint privacy', () => {
  const requests: { url: string; body: string | undefined }[] = [];

  beforeEach(() => {
    vi.resetModules();
    sessionStorage.clear();
    localStorage.clear();
    requests.length = 0;
    // Vitest's Node TextEncoder returns buffers from a different realm than jsdom.
    const encoder = new TextEncoder();
    vi.stubGlobal('TextEncoder', class {
      encode(value: string) { return new Uint8Array(encoder.encode(value)); }
    });
    vi.spyOn(Math, 'random').mockReturnValue(0); // Always select upstream's telemetry sample.
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, body: init?.body as string | undefined });
      return new Response(JSON.stringify(url.endsWith('/api/public/guest/identify')
        ? { guest_id: 73, action: 'cookie_hit' }
        : {}), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('identifies and refreshes without sending fingerprint data to third parties', async () => {
    const { useGuestIdentity } = await import('../use-guest-identity');
    const { result } = renderHook(() => useGuestIdentity());
    await waitFor(() => expect(result.current.guestId).toBe(73), { timeout: 10_000 });
    expect(result.current.isReturning).toBe(true);

    await act(async () => { await result.current.refresh(); });

    expect(requests.map(({ url }) => url)).toEqual([
      '/api/public/guest/identify', '/api/public/guest/identify',
    ]);
    for (const { body } of requests) {
      const payload = JSON.parse(body!);
      expect(payload.fingerprint_hash).toMatch(/^[a-f0-9]{32}$/);
      expect(Object.keys(payload.fingerprint_components).length).toBeGreaterThan(0);
    }
  }, 15_000);
});
