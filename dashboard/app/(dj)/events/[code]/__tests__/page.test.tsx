import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock next/navigation
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: () => ({ code: 'TEST' }),
}));

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Mock qrcode.react
vi.mock('qrcode.react', () => ({
  QRCodeSVG: ({ value }: { value: string }) => (
    <div data-testid="qr-code" data-value={value}>QR</div>
  ),
}));

// Mock SSE hook
vi.mock('@/lib/use-event-stream', () => ({
  useEventStream: () => ({ connected: false }),
}));

// Mock help
vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({
    helpMode: false, onboardingActive: false, currentStep: 0, activeSpotId: null,
    toggleHelpMode: vi.fn(), registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []), startOnboarding: vi.fn(),
    nextStep: vi.fn(), prevStep: vi.fn(), skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => true),
  }),
}));
vi.mock('@/components/help/HelpSpot', () => ({
  HelpSpot: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('@/components/help/HelpButton', () => ({
  HelpButton: () => null,
}));
vi.mock('@/components/help/OnboardingOverlay', () => ({
  OnboardingOverlay: () => null,
}));
vi.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => null,
}));
vi.mock('@/lib/tab-title', () => ({
  useTabTitle: () => {},
}));

// Variable-based auth mock
let mockIsAuthenticated = true;
let mockIsLoading = false;
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    isAuthenticated: mockIsAuthenticated,
    isLoading: mockIsLoading,
  }),
}));

// Capture props from child components
let capturedSongTabProps: Record<string, unknown> = {};
let capturedManageTabProps: Record<string, unknown> = {};
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- used inside vi.mock factory
let capturedQueueProps: Record<string, unknown> = {};

vi.mock('../components/SongManagementTab', () => ({
  SongManagementTab: (props: Record<string, unknown>) => {
    capturedSongTabProps = props;
    return <div data-testid="song-tab">SongTab</div>;
  },
}));
vi.mock('../components/EventManagementTab', () => ({
  EventManagementTab: (props: Record<string, unknown>) => {
    capturedManageTabProps = props;
    return <div data-testid="manage-tab">ManageTab</div>;
  },
}));
vi.mock('../components/RequestQueueSection', () => ({
  RequestQueueSection: (props: Record<string, unknown>) => {
    capturedQueueProps = props;
    return <div data-testid="queue-section">Queue</div>;
  },
}));
vi.mock('../components/PlayHistorySection', () => ({
  PlayHistorySection: () => <div data-testid="play-history">History</div>,
}));
vi.mock('../components/DeleteEventModal', () => ({
  DeleteEventModal: (props: { onConfirm: () => void; onCancel: () => void }) => (
    <div data-testid="delete-modal">
      <button onClick={props.onConfirm}>Confirm Delete</button>
      <button onClick={props.onCancel}>Cancel Delete</button>
    </div>
  ),
}));
vi.mock('../components/NowPlayingBadge', () => ({
  NowPlayingBadge: () => <div data-testid="now-playing-badge">NP</div>,
}));
vi.mock('../components/TidalLoginModal', () => ({
  TidalLoginModal: (props: { onCancel: () => void }) => (
    <div data-testid="tidal-login-modal">
      <button onClick={props.onCancel}>Cancel Tidal</button>
    </div>
  ),
}));
vi.mock('../components/BeatportLoginModal', () => ({
  BeatportLoginModal: (props: { onSubmit: (u: string, p: string) => Promise<void>; onCancel: () => void }) => (
    <div data-testid="beatport-login-modal">
      <button onClick={() => props.onSubmit('user', 'pass')}>Submit BP Login</button>
      <button onClick={props.onCancel}>Cancel BP</button>
    </div>
  ),
}));
vi.mock('../components/ServiceTrackPickerModal', () => ({
  ServiceTrackPickerModal: () => <div data-testid="track-picker-modal">Picker</div>,
}));
vi.mock('@/components/EventErrorCard', () => ({
  EventErrorCard: ({ error }: { error: { message: string; status: number } | null }) => (
    <div data-testid="error-card">{error?.status === 410 ? 'Expired' : error?.status === 404 ? 'Not Found' : 'Error'}</div>
  ),
}));

// Mock API
vi.mock('@/lib/api', () => ({
  api: {
    getEvent: vi.fn(),
    getRequests: vi.fn(),
    getPlayHistory: vi.fn(),
    getDisplaySettings: vi.fn(),
    getTidalStatus: vi.fn(),
    getBeatportStatus: vi.fn(),
    getNowPlaying: vi.fn(),
    getArchivedEvents: vi.fn(),
    updateRequestStatus: vi.fn(),
    acceptAllRequests: vi.fn(),
    updateEvent: vi.fn(),
    deleteEvent: vi.fn(),
    exportEventCsv: vi.fn(),
    exportPlayHistoryCsv: vi.fn(),
    setNowPlayingVisibility: vi.fn(),
    setAutoHideMinutes: vi.fn(),
    setRequestsOpen: vi.fn(),
    setKioskDisplayOnly: vi.fn(),
    updateTidalEventSettings: vi.fn(),
    startTidalAuth: vi.fn(),
    checkTidalAuth: vi.fn(),
    cancelTidalAuth: vi.fn(),
    disconnectTidal: vi.fn(),
    syncRequestToTidal: vi.fn(),
    searchTidal: vi.fn(),
    linkTidalTrack: vi.fn(),
    updateBeatportEventSettings: vi.fn(),
    loginBeatport: vi.fn(),
    disconnectBeatport: vi.fn(),
    searchBeatport: vi.fn(),
    linkBeatportTrack: vi.fn(),
    uploadEventBanner: vi.fn(),
    deleteEventBanner: vi.fn(),
    submitRequest: vi.fn(),
    deleteRequest: vi.fn(),
    refreshRequestMetadata: vi.fn(),
    rejectAllRequests: vi.fn(),
    bulkDeleteRequests: vi.fn(),
    getBridgeStatus: vi.fn(),
    sendBridgeCommand: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

import { api, ApiError } from '@/lib/api';
import type { SongRequest } from '@/lib/api';
import EventQueuePage from '../page';

function mockEvent(overrides = {}) {
  return {
    id: 1, code: 'TEST',
      join_code: 'TSETJO',
      collect_url: null, name: 'Test Event',
    created_at: '2026-01-01T00:00:00Z', expires_at: '2026-12-31T00:00:00Z',
    is_active: true, join_url: null, requests_open: true,
    tidal_sync_enabled: false, tidal_playlist_id: null,
    beatport_sync_enabled: false, beatport_playlist_id: null,
    banner_url: null, banner_kiosk_url: null, banner_colors: null,
    collection_opens_at: null, live_starts_at: null,
    submission_cap_per_guest: 15, collection_phase_override: null,
    archived_at: null, request_count: null, status: null,
    ...overrides,
  };
}

function mockRequest(overrides: Partial<SongRequest> = {}): SongRequest {
  return {
    id: 1, event_id: 1, song_title: 'Strobe', artist: 'deadmau5',
    source: 'spotify', source_url: null, artwork_url: null, note: null, nickname: null,
    status: 'new', created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z', is_duplicate: false, raw_search_query: null,
    sync_results_json: null, genre: null, bpm: null, musical_key: null,
    vote_count: 0, priority_score: null, ...overrides,
  };
}

function setupDefaultMocks() {
  vi.mocked(api.getEvent).mockResolvedValue(mockEvent());
  vi.mocked(api.getRequests).mockResolvedValue([]);
  vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.getDisplaySettings).mockResolvedValue({
    status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
    requests_open: true, kiosk_display_only: false,
  });
  vi.mocked(api.getTidalStatus).mockResolvedValue({
    linked: false, user_id: null, expires_at: null, integration_enabled: true,
  });
  vi.mocked(api.getBeatportStatus).mockResolvedValue({
    linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true,
  });
  vi.mocked(api.getNowPlaying).mockResolvedValue(null);
  vi.mocked(api.getBridgeStatus).mockResolvedValue({
    connected: false, device_name: null, last_seen: null,
    circuit_breaker_state: null, buffer_size: null, plugin_id: null,
    deck_count: null, uptime_seconds: null,
  });
  vi.mocked(api.sendBridgeCommand).mockResolvedValue({ command_id: 'test', command_type: 'ping' });
}

describe('EventQueuePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsAuthenticated = true;
    mockIsLoading = false;
    capturedSongTabProps = {};
    capturedManageTabProps = {};
    capturedQueueProps = {};
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe('Initial loading and auth guard', () => {
    it('redirects to /login when not authenticated', () => {
      mockIsAuthenticated = false;
      mockIsLoading = false;
      setupDefaultMocks();

      render(<EventQueuePage />);

      expect(mockPush).toHaveBeenCalledWith('/login');
    });

    it('shows Loading while auth is resolving', () => {
      mockIsLoading = true;
      mockIsAuthenticated = false;
      setupDefaultMocks();

      render(<EventQueuePage />);

      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('shows "Loading event..." during fetch', () => {
      vi.mocked(api.getEvent).mockImplementation(() => new Promise(() => {}));
      vi.mocked(api.getRequests).mockImplementation(() => new Promise(() => {}));
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
      vi.mocked(api.getDisplaySettings).mockResolvedValue({
        status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
        requests_open: true, kiosk_display_only: false,
      });
      vi.mocked(api.getTidalStatus).mockResolvedValue({
        linked: false, user_id: null, expires_at: null, integration_enabled: true,
      });
      vi.mocked(api.getBeatportStatus).mockResolvedValue({
        linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);

      render(<EventQueuePage />);

      expect(screen.getByText('Loading event...')).toBeInTheDocument();
    });

    it('renders event name after load', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);

      await screen.findByText('Test Event');
    });

    it('renders QR code', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);

      await screen.findByText('Test Event');
      expect(screen.getByTestId('qr-code')).toBeInTheDocument();
    });

    it('renders event join_code under the QR (not the collection code)', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);

      // The big bold code shown above the "Scan to join" QR is the join_code
      // — that's what the QR encodes. Collection code is the URL slug DJs
      // navigate by but is not the human-facing scan target.
      await waitFor(() => {
        expect(screen.getByText('TSETJO')).toBeInTheDocument();
      });
    });
  });

  describe('Error states', () => {
    it('shows error card on 404', async () => {
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Not found', 404));
      vi.mocked(api.getRequests).mockRejectedValue(new ApiError('Not found', 404));
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
      vi.mocked(api.getDisplaySettings).mockResolvedValue({
        status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
        requests_open: true, kiosk_display_only: false,
      });
      vi.mocked(api.getTidalStatus).mockResolvedValue({
        linked: false, user_id: null, expires_at: null, integration_enabled: true,
      });
      vi.mocked(api.getBeatportStatus).mockResolvedValue({
        linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);

      render(<EventQueuePage />);

      await waitFor(() => {
        expect(screen.getByTestId('error-card')).toBeInTheDocument();
        expect(screen.getByText('Not Found')).toBeInTheDocument();
      });
    });

    it('shows expired state on 410 with archived data', async () => {
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getRequests).mockResolvedValue([mockRequest()]);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
      vi.mocked(api.getDisplaySettings).mockResolvedValue({
        status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
        requests_open: true, kiosk_display_only: false,
      });
      vi.mocked(api.getTidalStatus).mockResolvedValue({
        linked: false, user_id: null, expires_at: null, integration_enabled: true,
      });
      vi.mocked(api.getBeatportStatus).mockResolvedValue({
        linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getArchivedEvents).mockResolvedValue([{
        ...mockEvent(), status: 'expired' as const, request_count: 1, archived_at: null,
      }]);

      render(<EventQueuePage />);

      await waitFor(() => {
        expect(screen.getByText('Test Event')).toBeInTheDocument();
        expect(screen.getByText('expired')).toBeInTheDocument();
      });
    });

    it('shows error card on 410 without archived match', async () => {
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getRequests).mockResolvedValue([]);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
      vi.mocked(api.getDisplaySettings).mockResolvedValue({
        status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
        requests_open: true, kiosk_display_only: false,
      });
      vi.mocked(api.getTidalStatus).mockResolvedValue({
        linked: false, user_id: null, expires_at: null, integration_enabled: true,
      });
      vi.mocked(api.getBeatportStatus).mockResolvedValue({
        linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getArchivedEvents).mockResolvedValue([]); // No match

      render(<EventQueuePage />);

      await waitFor(() => {
        expect(screen.getByTestId('error-card')).toBeInTheDocument();
      });
    });
  });

  describe('Polling loop', () => {
    it('polls every 3 seconds', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();

      render(<EventQueuePage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(api.getEvent).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(api.getEvent).toHaveBeenCalledTimes(2);

      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(api.getEvent).toHaveBeenCalledTimes(3);
    });

    it('stops on 404', async () => {
      vi.useFakeTimers();
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Not found', 404));
      vi.mocked(api.getRequests).mockResolvedValue([]);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
      vi.mocked(api.getDisplaySettings).mockResolvedValue({
        status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
        requests_open: true, kiosk_display_only: false,
      });
      vi.mocked(api.getTidalStatus).mockResolvedValue({
        linked: false, user_id: null, expires_at: null, integration_enabled: true,
      });
      vi.mocked(api.getBeatportStatus).mockResolvedValue({
        linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);

      render(<EventQueuePage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      const callCount = vi.mocked(api.getEvent).mock.calls.length;

      await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
      expect(api.getEvent).toHaveBeenCalledTimes(callCount);
    });

    it('continues on transient error', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      vi.mocked(api.getEvent)
        .mockResolvedValueOnce(mockEvent())
        .mockRejectedValueOnce(new Error('Transient'))
        .mockResolvedValue(mockEvent());

      render(<EventQueuePage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(api.getEvent).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(api.getEvent).toHaveBeenCalledTimes(2);

      // Should still poll after transient error
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(api.getEvent).toHaveBeenCalledTimes(3);
    });
  });

  describe('Tab switching', () => {
    it('defaults to songs tab', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      expect(screen.getByTestId('song-tab')).toBeInTheDocument();
    });

    it('switches to manage tab', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByText('Event Management'));

      expect(screen.getByTestId('manage-tab')).toBeInTheDocument();
    });

    it('switches back to songs tab', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByText('Event Management'));
      fireEvent.click(screen.getByText('Song Management'));

      expect(screen.getByTestId('song-tab')).toBeInTheDocument();
    });
  });

  describe('Compact mode', () => {
    it('toggles via button and persists to localStorage', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const container = screen.getByText('Test Event').closest('.container');
      expect(container?.classList.contains('compact')).toBe(false);

      fireEvent.click(screen.getByLabelText('Compact mode off'));

      expect(container?.classList.contains('compact')).toBe(true);

      // Toggle back
      fireEvent.click(screen.getByLabelText('Compact mode on'));

      expect(container?.classList.contains('compact')).toBe(false);
    });
  });

  describe('Action error auto-dismiss', () => {
    it('auto-dismisses after 5s', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      vi.mocked(api.getRequests).mockResolvedValue([mockRequest()]);
      vi.mocked(api.updateRequestStatus).mockRejectedValue(new ApiError('Status error', 400));

      render(<EventQueuePage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Trigger an error via the update handler
      const onUpdateStatus = capturedSongTabProps.onUpdateStatus as (id: number, s: string) => Promise<void>;
      await act(async () => { await onUpdateStatus(1, 'accepted'); });

      expect(screen.getByText('Status error')).toBeInTheDocument();

      // Advance 5s — error should dismiss
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(screen.queryByText('Status error')).not.toBeInTheDocument();
    });
  });

  describe('Request status actions', () => {
    it('passes onUpdateStatus to SongTab', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      expect(typeof capturedSongTabProps.onUpdateStatus).toBe('function');
    });

    it('calls updateRequestStatus via handler', async () => {
      setupDefaultMocks();
      vi.mocked(api.getRequests).mockResolvedValue([mockRequest()]);
      vi.mocked(api.updateRequestStatus).mockResolvedValue(mockRequest({ status: 'accepted' }));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onUpdateStatus = capturedSongTabProps.onUpdateStatus as (id: number, s: string) => Promise<void>;
      await act(async () => { await onUpdateStatus(1, 'accepted'); });

      expect(api.updateRequestStatus).toHaveBeenCalledWith(1, 'accepted');
    });

    it('shows error on status update failure', async () => {
      setupDefaultMocks();
      vi.mocked(api.getRequests).mockResolvedValue([mockRequest()]);
      vi.mocked(api.updateRequestStatus).mockRejectedValue(new ApiError('Invalid transition', 400));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onUpdateStatus = capturedSongTabProps.onUpdateStatus as (id: number, s: string) => Promise<void>;
      await act(async () => { await onUpdateStatus(1, 'played'); });

      expect(screen.getByText('Invalid transition')).toBeInTheDocument();
    });
  });

  describe('Accept all requests', () => {
    it('calls acceptAllRequests', async () => {
      setupDefaultMocks();
      vi.mocked(api.acceptAllRequests).mockResolvedValue({ status: 'ok', accepted_count: 1 });
      vi.mocked(api.getRequests).mockResolvedValue([mockRequest({ status: 'accepted' })]);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onAcceptAll = capturedSongTabProps.onAcceptAll as () => Promise<void>;
      await act(async () => { await onAcceptAll(); });

      expect(api.acceptAllRequests).toHaveBeenCalledWith('TEST');
    });

    it('shows error on failure', async () => {
      setupDefaultMocks();
      vi.mocked(api.acceptAllRequests).mockRejectedValue(new ApiError('No requests', 400));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onAcceptAll = capturedSongTabProps.onAcceptAll as () => Promise<void>;
      await act(async () => { await onAcceptAll(); });

      expect(screen.getByText('No requests')).toBeInTheDocument();
    });
  });

  describe('Edit expiry', () => {
    it('shows edit form on click', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByRole('button', { name: 'Edit' }));

      expect(screen.getByDisplayValue(/2026/)).toBeInTheDocument();
    });

    it('saves new expiry', async () => {
      setupDefaultMocks();
      vi.mocked(api.updateEvent).mockResolvedValue(mockEvent({ expires_at: '2027-06-01T00:00:00Z' }));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
      fireEvent.change(screen.getByDisplayValue(/2026/), {
        target: { value: '2027-06-01T00:00' },
      });
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      });

      expect(api.updateEvent).toHaveBeenCalledWith('TEST', expect.objectContaining({
        expires_at: expect.stringContaining('2027'),
      }));
    });

    it('cancels editing', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
      expect(screen.getByDisplayValue(/2026/)).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      expect(screen.queryByDisplayValue(/2026-12/)).not.toBeInTheDocument();
      expect(api.updateEvent).not.toHaveBeenCalled();
    });
  });

  describe('Delete event', () => {
    it('shows delete modal', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

      expect(screen.getByTestId('delete-modal')).toBeInTheDocument();
    });

    it('deletes and redirects on confirm', async () => {
      setupDefaultMocks();
      vi.mocked(api.deleteEvent).mockResolvedValue(undefined);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
      await act(async () => {
        fireEvent.click(screen.getByText('Confirm Delete'));
      });

      expect(api.deleteEvent).toHaveBeenCalledWith('TEST');
      expect(mockPush).toHaveBeenCalledWith('/dashboard');
    });

    it('shows error on failure', async () => {
      setupDefaultMocks();
      vi.mocked(api.deleteEvent).mockRejectedValue(new ApiError('Cannot delete', 400));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
      await act(async () => {
        fireEvent.click(screen.getByText('Confirm Delete'));
      });

      expect(screen.getByText('Cannot delete')).toBeInTheDocument();
      expect(mockPush).not.toHaveBeenCalledWith('/events');
    });
  });

  describe('CSV export', () => {
    it('calls exportEventCsv', async () => {
      setupDefaultMocks();
      // Force expired state to show export button
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getArchivedEvents).mockResolvedValue([{
        ...mockEvent(), status: 'expired' as const, request_count: 1, archived_at: null,
      }]);
      vi.mocked(api.getRequests).mockResolvedValue([mockRequest()]);
      vi.mocked(api.exportEventCsv).mockResolvedValue(undefined);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
      });

      expect(api.exportEventCsv).toHaveBeenCalledWith('TEST');
    });
  });

  describe('Display settings via ManageTab', () => {
    it('passes toggle handlers to ManageTab', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByText('Event Management'));

      expect(typeof capturedManageTabProps.onToggleRequests).toBe('function');
      expect(typeof capturedManageTabProps.onToggleNowPlaying).toBe('function');
      expect(typeof capturedManageTabProps.onToggleDisplayOnly).toBe('function');
      expect(typeof capturedManageTabProps.onBannerSelect).toBe('function');
    });

    it('onToggleRequests calls setRequestsOpen', async () => {
      setupDefaultMocks();
      vi.mocked(api.setRequestsOpen).mockResolvedValue(undefined as never);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onToggleRequests = capturedManageTabProps.onToggleRequests as () => Promise<void>;
      await act(async () => { await onToggleRequests(); });

      expect(api.setRequestsOpen).toHaveBeenCalledWith('TEST', false);
    });

    it('onToggleNowPlaying calls setNowPlayingVisibility', async () => {
      setupDefaultMocks();
      vi.mocked(api.setNowPlayingVisibility).mockResolvedValue(undefined as never);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onToggleNowPlaying = capturedManageTabProps.onToggleNowPlaying as () => Promise<void>;
      await act(async () => { await onToggleNowPlaying(); });

      expect(api.setNowPlayingVisibility).toHaveBeenCalledWith('TEST', true);
    });

    it('onToggleDisplayOnly calls setKioskDisplayOnly', async () => {
      setupDefaultMocks();
      vi.mocked(api.setKioskDisplayOnly).mockResolvedValue(undefined as never);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onToggleDisplayOnly = capturedManageTabProps.onToggleDisplayOnly as () => Promise<void>;
      await act(async () => { await onToggleDisplayOnly(); });

      expect(api.setKioskDisplayOnly).toHaveBeenCalledWith('TEST', true);
    });
  });

  describe('Tidal auth flow', () => {
    it('starts auth and shows modal', async () => {
      setupDefaultMocks();
      vi.mocked(api.startTidalAuth).mockResolvedValue({
        verification_url: 'https://tidal.com/device',
        user_code: 'ABCD1234',
        message: 'ok',
      });

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onConnectTidal = capturedManageTabProps.onConnectTidal as () => Promise<void>;
      await act(async () => { await onConnectTidal(); });

      expect(api.startTidalAuth).toHaveBeenCalled();
      expect(screen.getByTestId('tidal-login-modal')).toBeInTheDocument();
    });

    it('polls checkTidalAuth every 2s', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      vi.mocked(api.startTidalAuth).mockResolvedValue({
        verification_url: 'https://tidal.com/device',
        user_code: 'ABCD1234',
        message: 'ok',
      });
      vi.mocked(api.checkTidalAuth).mockResolvedValue({ complete: false });

      render(<EventQueuePage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      fireEvent.click(screen.getByText('Event Management'));

      const onConnectTidal = capturedManageTabProps.onConnectTidal as () => Promise<void>;
      await act(async () => { await onConnectTidal(); });

      // Advance 2s for first poll
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
      expect(api.checkTidalAuth).toHaveBeenCalledTimes(1);

      // Advance 2s for second poll
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
      expect(api.checkTidalAuth).toHaveBeenCalledTimes(2);
    });

    it('cancels auth', async () => {
      setupDefaultMocks();
      vi.mocked(api.startTidalAuth).mockResolvedValue({
        verification_url: 'https://tidal.com/device',
        user_code: 'ABCD1234',
        message: 'ok',
      });
      vi.mocked(api.cancelTidalAuth).mockResolvedValue({ status: 'ok', message: 'cancelled' });

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onConnectTidal = capturedManageTabProps.onConnectTidal as () => Promise<void>;
      await act(async () => { await onConnectTidal(); });

      await act(async () => {
        fireEvent.click(screen.getByText('Cancel Tidal'));
      });

      expect(api.cancelTidalAuth).toHaveBeenCalled();
    });
  });

  describe('Beatport auth flow', () => {
    it('opens login modal', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onConnectBeatport = capturedManageTabProps.onConnectBeatport as () => void;
      act(() => { onConnectBeatport(); });

      expect(screen.getByTestId('beatport-login-modal')).toBeInTheDocument();
    });

    it('calls loginBeatport', async () => {
      setupDefaultMocks();
      vi.mocked(api.loginBeatport).mockResolvedValue({ status: 'ok', message: 'logged in' });
      vi.mocked(api.getBeatportStatus).mockResolvedValue({
        linked: true, expires_at: null, configured: true, subscription: 'pro', integration_enabled: true,
      });

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onConnectBeatport = capturedManageTabProps.onConnectBeatport as () => void;
      act(() => { onConnectBeatport(); });

      await act(async () => {
        fireEvent.click(screen.getByText('Submit BP Login'));
      });

      expect(api.loginBeatport).toHaveBeenCalledWith('user', 'pass');
    });
  });

  describe('Banner upload', () => {
    it('passes onBannerSelect to ManageTab', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      expect(typeof capturedManageTabProps.onBannerSelect).toBe('function');
    });

    it('onBannerSelect calls uploadEventBanner with file', async () => {
      setupDefaultMocks();
      vi.mocked(api.uploadEventBanner).mockResolvedValue(mockEvent({
        banner_url: '/uploads/banners/test.webp',
        banner_kiosk_url: '/uploads/banners/test_kiosk.webp',
      }) as never);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const file = new File(['fake-image'], 'banner.png', { type: 'image/png' });
      const onBannerSelect = capturedManageTabProps.onBannerSelect as (
        e: React.ChangeEvent<HTMLInputElement>,
      ) => Promise<void>;
      await act(async () => {
        await onBannerSelect({
          target: { files: [file] },
        } as unknown as React.ChangeEvent<HTMLInputElement>);
      });

      expect(api.uploadEventBanner).toHaveBeenCalledWith('TEST', file);
    });
  });

  describe('Now playing badge', () => {
    it('shows badge when bridge has now-playing', async () => {
      setupDefaultMocks();
      vi.mocked(api.getNowPlaying).mockResolvedValue({
        title: 'Track', artist: 'Artist', album: null, album_art_url: null,
        spotify_uri: null, started_at: new Date().toISOString(),
        source: 'stagelinq', matched_request_id: null, bridge_connected: true,
      });

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      expect(screen.getByTestId('now-playing-badge')).toBeInTheDocument();
    });

    it('hides badge when expired', async () => {
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getArchivedEvents).mockResolvedValue([{
        ...mockEvent(), status: 'expired' as const, request_count: 0, archived_at: null,
      }]);
      vi.mocked(api.getRequests).mockResolvedValue([]);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
      vi.mocked(api.getDisplaySettings).mockResolvedValue({
        status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
        requests_open: true, kiosk_display_only: false,
      });
      vi.mocked(api.getTidalStatus).mockResolvedValue({
        linked: false, user_id: null, expires_at: null, integration_enabled: true,
      });
      vi.mocked(api.getBeatportStatus).mockResolvedValue({
        linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue({
        title: 'Track', artist: 'Artist', album: null, album_art_url: null,
        spotify_uri: null, started_at: new Date().toISOString(),
        source: 'stagelinq', matched_request_id: null, bridge_connected: true,
      });

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      expect(screen.queryByTestId('now-playing-badge')).not.toBeInTheDocument();
    });
  });

  describe('Expired event features', () => {
    it('shows RequestQueueSection directly for expired events', async () => {
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getArchivedEvents).mockResolvedValue([{
        ...mockEvent(), status: 'expired' as const, request_count: 1, archived_at: null,
      }]);
      vi.mocked(api.getRequests).mockResolvedValue([mockRequest()]);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
      vi.mocked(api.getDisplaySettings).mockResolvedValue({
        status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
        requests_open: true, kiosk_display_only: false,
      });
      vi.mocked(api.getTidalStatus).mockResolvedValue({
        linked: false, user_id: null, expires_at: null, integration_enabled: true,
      });
      vi.mocked(api.getBeatportStatus).mockResolvedValue({
        linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      // Expired events show queue section directly, no tabs
      expect(screen.getByTestId('queue-section')).toBeInTheDocument();
      expect(screen.getByTestId('play-history')).toBeInTheDocument();
      expect(screen.queryByText('Song Management')).not.toBeInTheDocument();
    });

    it('hides QR code for expired events', async () => {
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getArchivedEvents).mockResolvedValue([{
        ...mockEvent(), status: 'expired' as const, request_count: 0, archived_at: null,
      }]);
      vi.mocked(api.getRequests).mockResolvedValue([]);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
      vi.mocked(api.getDisplaySettings).mockResolvedValue({
        status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
        requests_open: true, kiosk_display_only: false,
      });
      vi.mocked(api.getTidalStatus).mockResolvedValue({
        linked: false, user_id: null, expires_at: null, integration_enabled: true,
      });
      vi.mocked(api.getBeatportStatus).mockResolvedValue({
        linked: false, expires_at: null, configured: false, subscription: null, integration_enabled: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      expect(screen.queryByTestId('qr-code')).not.toBeInTheDocument();
    });
  });

  describe('Delete request', () => {
    it('calls deleteRequest via handler', async () => {
      setupDefaultMocks();
      vi.mocked(api.getRequests).mockResolvedValue([mockRequest()]);
      vi.mocked(api.deleteRequest).mockResolvedValue(undefined);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onDeleteRequest = capturedSongTabProps.onDeleteRequest as (id: number) => Promise<void>;
      await act(async () => { await onDeleteRequest(1); });

      expect(api.deleteRequest).toHaveBeenCalledWith(1);
    });
  });

  describe('Refresh metadata', () => {
    it('calls refreshRequestMetadata via handler', async () => {
      setupDefaultMocks();
      vi.mocked(api.getRequests).mockResolvedValue([mockRequest()]);
      vi.mocked(api.refreshRequestMetadata).mockResolvedValue(
        mockRequest({ genre: 'Electronic', bpm: 128 }),
      );

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onRefreshMetadata = capturedSongTabProps.onRefreshMetadata as (id: number) => Promise<void>;
      await act(async () => { await onRefreshMetadata(1); });

      expect(api.refreshRequestMetadata).toHaveBeenCalledWith(1);
    });
  });

  describe('Reject all', () => {
    it('calls rejectAllRequests via handler', async () => {
      setupDefaultMocks();
      vi.mocked(api.rejectAllRequests).mockResolvedValue({ status: 'ok', count: 0 });
      vi.mocked(api.getRequests).mockResolvedValue([]);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onRejectAll = capturedSongTabProps.onRejectAll as () => Promise<void>;
      await act(async () => { await onRejectAll(); });

      expect(api.rejectAllRequests).toHaveBeenCalledWith('TEST');
    });
  });

  describe('Back link', () => {
    it('shows back link to events', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const backLink = screen.getByText(/Back to Events/);
      expect(backLink.closest('a')).toHaveAttribute('href', '/dashboard');
    });
  });
});
