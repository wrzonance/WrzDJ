import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({ code: 'TEST' }),
}));

// Mock auth
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ isAuthenticated: true, isLoading: false, role: 'dj', logout: vi.fn() }),
}));

// Mock qrcode.react
vi.mock('qrcode.react', () => ({
  QRCodeSVG: ({ value }: { value: string }) => <div data-testid="qr-code">{value}</div>,
}));

// Mock complex child components to prevent deep rendering
vi.mock('../components/SongManagementTab', () => ({
  SongManagementTab: () => <div data-testid="song-tab">SongTab</div>,
}));

vi.mock('../components/EventManagementTab', () => ({
  EventManagementTab: () => <div data-testid="manage-tab">ManageTab</div>,
}));

vi.mock('../components/DeleteEventModal', () => ({
  DeleteEventModal: () => null,
}));

vi.mock('../components/NowPlayingBadge', () => ({
  NowPlayingBadge: () => null,
}));

vi.mock('../components/TidalLoginModal', () => ({
  TidalLoginModal: () => null,
}));

vi.mock('../components/BeatportLoginModal', () => ({
  BeatportLoginModal: () => null,
}));

vi.mock('../components/ServiceTrackPickerModal', () => ({
  ServiceTrackPickerModal: () => null,
}));

vi.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => null,
}));

vi.mock('@/lib/tab-title', () => ({
  useTabTitle: () => {},
}));

vi.mock('../components/RequestQueueSection', () => ({
  RequestQueueSection: () => null,
}));

vi.mock('../components/PlayHistorySection', () => ({
  PlayHistorySection: () => null,
}));

// Mock api
vi.mock('@/lib/api', () => ({
  api: {
    getEvent: vi.fn().mockResolvedValue({
      id: 1, name: 'Test Event', code: 'TEST',
      expires_at: '2026-12-31T00:00:00Z', is_active: true,
      tidal_sync_enabled: false, beatport_sync_enabled: false,
    }),
    getRequests: vi.fn().mockResolvedValue({
      requests: [], total: 0, limit: 100, offset: 0, sort: 'date_requested', direction: 'desc',
    }),
    getPlayHistory: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    getDisplaySettings: vi.fn().mockResolvedValue({
      now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
      requests_open: true, kiosk_display_only: false,
    }),
    getTidalStatus: vi.fn().mockResolvedValue({ linked: false, user_id: null, expires_at: null, integration_enabled: true }),
    getBeatportStatus: vi.fn().mockResolvedValue({ linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true }),
    getNowPlaying: vi.fn().mockResolvedValue(null),
    getBridgeStatus: vi.fn().mockResolvedValue({
      connected: false, device_name: null, last_seen: null,
      circuit_breaker_state: null, buffer_size: null, plugin_id: null,
      deck_count: null, uptime_seconds: null,
    }),
    sendBridgeCommand: vi.fn().mockResolvedValue(undefined),
  },
  ApiError: class extends Error { status: number; constructor(m: string, s: number) { super(m); this.status = s; } },
}));

// localStorage mock
const store: Record<string, string> = {};
const localStorageMock = {
  getItem: (key: string) => store[key] ?? null,
  setItem: (key: string, value: string) => { store[key] = value; },
  removeItem: (key: string) => { delete store[key]; },
  clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
  get length() { return Object.keys(store).length; },
  key: (i: number) => Object.keys(store)[i] ?? null,
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true });

import EventQueuePage from '../page';
import { HelpProvider } from '@/lib/help/HelpContext';

function renderWithProviders() {
  return render(
    <HelpProvider>
      <EventQueuePage />
    </HelpProvider>
  );
}

describe('Event detail page — tab navigation', () => {
  beforeEach(() => {
    localStorageMock.clear();
    localStorageMock.setItem('wrzdj-help-seen-event-songs', '1');
    localStorageMock.setItem('wrzdj-help-seen-event-manage', '1');
  });

  it('switching to manage tab renders manage content', async () => {
    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText('Event Management')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Event Management'));

    await waitFor(() => {
      expect(screen.getByTestId('manage-tab')).toBeVisible();
    });
  });
});
