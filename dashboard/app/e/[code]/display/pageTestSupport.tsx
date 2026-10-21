import { beforeEach, afterEach, vi } from 'vitest';
const mockEventStream = vi.hoisted(() => ({
  handlers: null as Record<string, (data: unknown) => void> | null,
}));

export function getMockEventStream() {
  return mockEventStream;
}

// Mock next/navigation
export const mockPush = vi.fn();
export let mockDisplayCode = 'TEST123';
export function setMockDisplayCode(code: string) {
  mockDisplayCode = code;
}
vi.mock('next/navigation', () => ({
  useParams: () => ({ code: mockDisplayCode }),
  useRouter: () => ({ push: mockPush }),
}));

// Mock qrcode.react
vi.mock('qrcode.react', () => ({
  QRCodeSVG: ({ value }: { value: string }) => (
    <div data-testid="qr-code" data-value={value}>QR Code</div>
  ),
}));

// Mock localStorage
export const localStorageStore: Record<string, string> = {};
export const localStorageMock = {
  getItem: (key: string) => localStorageStore[key] ?? null,
  setItem: (key: string, value: string) => { localStorageStore[key] = value; },
  removeItem: (key: string) => { delete localStorageStore[key]; },
  clear: () => { for (const key of Object.keys(localStorageStore)) delete localStorageStore[key]; },
};
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, writable: true, configurable: true });

// Mock SSE hook
vi.mock('@/lib/use-event-stream', () => ({
  useEventStream: (_code: string, handlers: Record<string, (data: unknown) => void>) => {
    mockEventStream.handlers = handlers;
    return { connected: false };
  },
}));

// Mock RequestModal
vi.mock('./components/RequestModal', () => ({
  RequestModal: () => <div data-testid="request-modal">Modal</div>,
}));

// Mock API responses
export const mockKioskDisplay = {
  event: { code: 'TEST123', name: 'Test Event' },
  qr_join_url: 'https://example.com/join/TEST123',
  accepted_queue: [
    { id: 1, title: 'Song 1', artist: 'Artist 1', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
    { id: 2, title: 'Song 2', artist: 'Artist 2', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
  ],
  accepted_queue_total: 2,
  now_playing: null,
  now_playing_hidden: false,
  requests_open: true,
  updated_at: new Date().toISOString(),
  banner_url: null,
  banner_kiosk_url: null,
  banner_colors: null,
  kiosk_display_only: false,
};

export const mockNowPlaying = {
  title: 'Currently Playing Song',
  artist: 'Current Artist',
  album: 'Current Album',
  album_art_url: 'https://example.com/art.jpg',
  spotify_uri: null,
  started_at: new Date().toISOString(),
  source: 'stagelinq',
  matched_request_id: null,
  bridge_connected: true,
};

export const mockPlayHistory = {
  items: [
    { id: 1, title: 'History Song 1', artist: 'History Artist 1', album: null, album_art_url: null, spotify_uri: null, matched_request_id: null, source: 'stagelinq', started_at: new Date().toISOString(), ended_at: null, play_order: 1 },
    { id: 2, title: 'History Song 2', artist: 'History Artist 2', album: null, album_art_url: null, spotify_uri: null, matched_request_id: 1, source: 'stagelinq', started_at: new Date().toISOString(), ended_at: null, play_order: 2 },
  ],
  total: 2,
};

// Mock API module
vi.mock('@/lib/api', () => ({
  api: {
    getKioskDisplay: vi.fn(),
    getNowPlaying: vi.fn(),
    getPlayHistory: vi.fn(),
    getKioskAssignment: vi.fn(),
    setKioskSession: vi.fn(),
    search: vi.fn(),
    submitRequest: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  PUBLIC_PAGE_MAX: 500,
}));

import { api } from '@/lib/api';

export function setupDefaultMocks() {
  vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
  vi.mocked(api.getNowPlaying).mockResolvedValue(null);
  vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
}



beforeEach(() => {
    vi.resetAllMocks();
    mockDisplayCode = 'TEST123';
    mockEventStream.handlers = null;
    localStorageMock.clear();
  });

afterEach(() => {
    vi.useRealTimers();
  });
