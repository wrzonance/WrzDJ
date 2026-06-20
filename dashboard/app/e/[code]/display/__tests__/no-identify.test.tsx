import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import KioskDisplayPage from '../page';
import { api } from '@/lib/api';

vi.mock('next/navigation', () => ({
  useParams: () => ({ code: 'TEST01' }),
  useRouter: () => ({ push: vi.fn() }),
}));

// Mock localStorage (required by page's session token logic)
const localStorageStore: Record<string, string> = {};
const localStorageMock = {
  getItem: (key: string) => localStorageStore[key] ?? null,
  setItem: (key: string, value: string) => { localStorageStore[key] = value; },
  removeItem: (key: string) => { delete localStorageStore[key]; },
  clear: () => { for (const key of Object.keys(localStorageStore)) delete localStorageStore[key]; },
};
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, writable: true, configurable: true });

// thumbmarkjs mock: keeps module resolution clean if useGuestIdentity is ever
// accidentally re-imported; the hook is intentionally absent from this page.
vi.mock('@thumbmarkjs/thumbmarkjs', () => ({
  setOption: vi.fn(),
  getFingerprint: vi.fn().mockResolvedValue({ hash: 'testhash', data: {} }),
}));

// Mock SSE hook
vi.mock('@/lib/use-event-stream', () => ({
  useEventStream: () => ({ connected: false }),
}));

// Mock QR code (uses canvas, not available in jsdom)
vi.mock('qrcode.react', () => ({
  QRCodeSVG: ({ value }: { value: string }) => <div data-testid="qr-code" data-value={value}>QR</div>,
}));

// Mock RequestModal
vi.mock('../components/RequestModal', () => ({
  RequestModal: () => <div data-testid="request-modal">Modal</div>,
}));

vi.mock('@/lib/api', () => ({
  api: {
    getKioskDisplay: vi.fn().mockResolvedValue({
      event: { code: 'TEST01', name: 'Test' },
      qr_join_url: 'http://x',
      accepted_queue: [],
      accepted_queue_total: 0,
      now_playing: null,
      now_playing_hidden: false,
      requests_open: true,
      kiosk_display_only: false,
      updated_at: new Date().toISOString(),
      banner_url: null,
      banner_kiosk_url: null,
      banner_colors: null,
    }),
    getNowPlaying: vi.fn().mockResolvedValue(null),
    getPlayHistory: vi.fn().mockResolvedValue({ items: [] }),
    getKioskAssignment: vi.fn(),
    setKioskSession: vi.fn(),
  },
  ApiError: class extends Error { status = 0; },
  PUBLIC_PAGE_MAX: 500,
}));

describe('KioskDisplayPage (F4)', () => {
  const mockFetch = vi.fn();
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ guest_id: 1, action: 'create' }),
      headers: { get: () => null },
    });
    global.fetch = mockFetch as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does NOT call /api/public/guest/identify (kiosk stays anonymous)', async () => {
    render(<KioskDisplayPage />);
    await waitFor(() => {
      expect(api.getKioskDisplay).toHaveBeenCalled();
    });
    const identifyCalls = mockFetch.mock.calls.filter(([url]) =>
      String(url).includes('/api/public/guest/identify'),
    );
    expect(identifyCalls).toHaveLength(0);
  });
});
