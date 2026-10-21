import { registerPageErrorsAndSettings } from './page-errors-and-settings.cases';
import { registerPageActions } from './page-actions.cases';
import { registerProviderAndDisplay } from './page-provider-and-display.cases';
import { registerRequestList } from './page-request-list.cases';
import type { EventPageTestContext } from './page-test-context';
import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock next/navigation
const mockPush = vi.fn();
const eventPageTestState = {
  mockEventCode: 'TEST', mockIsAuthenticated: true, mockIsLoading: false, mockRole: 'dj',
  capturedSongTabProps: {} as Record<string, unknown>, capturedManageTabProps: {} as Record<string, unknown>,
};

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: () => ({ code: eventPageTestState.mockEventCode }),
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
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    isAuthenticated: eventPageTestState.mockIsAuthenticated,
    isLoading: eventPageTestState.mockIsLoading,
    role: eventPageTestState.mockRole,
  }),
}));

vi.mock('../components/requests/SongManagementTab', () => ({
  SongManagementTab: (props: Record<string, unknown>) => {
    const requestQueue = props.requestQueue as Record<string, unknown>;
    eventPageTestState.capturedSongTabProps = {
      ...props,
      requestQueue: {
        ...requestQueue,
        ...(requestQueue.toolbar as Record<string, unknown>),
        ...(requestQueue.rowActions as Record<string, unknown>),
      },
    };
    return <div data-testid="song-tab">SongTab</div>;
  },
}));
vi.mock('../components/management/EventManagementTab', () => ({
  EventManagementTab: (props: Record<string, unknown>) => {
    eventPageTestState.capturedManageTabProps = {
      ...props,
      ...(props.kiosk as Record<string, unknown>),
      ...(props.providers as Record<string, unknown>),
      ...(props.customization as Record<string, unknown>),
      ...(props.preEvent as Record<string, unknown>),
    };
    return <div data-testid="manage-tab">ManageTab</div>;
  },
}));
vi.mock('../components/voting/PreEventVotingTab', () => ({
  default: ({ event }: { event: { phase: string } }) => (
    <div data-testid="pre-event-tab">phase:{event.phase}</div>
  ),
}));
vi.mock('../components/requests/RequestQueueSection', () => ({
  RequestQueueSection: () => <div data-testid="queue-section">Queue</div>,
}));
vi.mock('../components/requests/PlayHistorySection', () => ({
  PlayHistorySection: (props: { onExport: () => void }) => (
    <div data-testid="play-history">
      History
      <button onClick={props.onExport}>Export Play History</button>
    </div>
  ),
}));
vi.mock('../components/management/DeleteEventModal', () => ({
  DeleteEventModal: (props: { onConfirm: () => void; onCancel: () => void }) => (
    <div data-testid="delete-modal">
      <button onClick={props.onConfirm}>Confirm Delete</button>
      <button onClick={props.onCancel}>Cancel Delete</button>
    </div>
  ),
}));
vi.mock('../components/requests/NowPlayingBadge', () => ({
  NowPlayingBadge: () => <div data-testid="now-playing-badge">NP</div>,
}));
vi.mock('../components/providers/TidalLoginModal', () => ({
  TidalLoginModal: (props: { onCancel: () => void }) => (
    <div data-testid="tidal-login-modal">
      <button onClick={props.onCancel}>Cancel Tidal</button>
    </div>
  ),
}));
vi.mock('../components/providers/BeatportLoginModal', () => ({
  BeatportLoginModal: (props: { onSubmit: (u: string, p: string) => Promise<void>; onCancel: () => void }) => (
    <div data-testid="beatport-login-modal">
      <button onClick={() => props.onSubmit('user', 'pass')}>Submit BP Login</button>
      <button onClick={props.onCancel}>Cancel BP</button>
    </div>
  ),
}));
vi.mock('../components/providers/ServiceTrackPickerModal', () => ({
  ServiceTrackPickerModal: () => <div data-testid="track-picker-modal">Picker</div>,
}));
vi.mock('@/components/EventErrorCard', () => ({
  EventErrorCard: ({ error }: { error: { message: string; status: number } | null }) => (
    <div data-testid="error-card">{error?.status === 410 ? 'Expired' : error?.status === 404 ? 'Not Found' : 'Error'}</div>
  ),
}));

// Mock API
vi.mock('@/lib/api', () => ({
  // useEventRequests → load-all-pages imports PUBLIC_PAGE_MAX; vitest throws on
  // any undefined named export of a mocked module, so it must be provided here.
  PUBLIC_PAGE_MAX: 500,
  api: {
    getEvent: vi.fn(),
    getRequests: vi.fn(),
    getPlayHistory: vi.fn(),
    getDisplaySettings: vi.fn(),
    getCollectionSettings: vi.fn(),
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
import type { Event, SongRequest, RequestListResponse } from '@/lib/api';
import EventQueuePage from '../page';

function mockEvent(overrides = {}) {
  return {
    id: 1, code: 'TEST',
      join_code: 'TSETJO',
      collect_url: null, name: 'Test Event',
    created_at: '2026-01-01T00:00:00Z', expires_at: '2026-12-31T00:00:00Z',
    is_active: true, join_url: null, requests_open: true,
    frictionless_join: false,
    tidal_sync_enabled: false, tidal_playlist_id: null,
    beatport_sync_enabled: false, beatport_playlist_id: null,
    banner_url: null, banner_kiosk_url: null, banner_colors: null,
    collection_opens_at: null, live_starts_at: null,
    submission_cap_per_guest: 15, collection_phase_override: null,
    archived_at: null, request_count: null, status: null,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function mockRequest(overrides: Partial<SongRequest> = {}): SongRequest {
  return {
    id: 1, event_id: 1, song_title: 'Strobe', artist: 'deadmau5',
    source: 'spotify', source_url: null, artwork_url: null, note: null, nickname: null,
    status: 'new', created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z', accepted_at: null, is_duplicate: false, raw_search_query: null,
    sync_results_json: null, genre: null, bpm: null, musical_key: null,
    vote_count: 0, priority_score: null, ...overrides,
  };
}

/** Wrap request rows in the #478 paginated envelope returned by getRequests. */
function mockRequestList(
  requests: SongRequest[] = [],
  overrides: Partial<RequestListResponse> = {},
): RequestListResponse {
  return {
    requests,
    total: requests.length,
    limit: 100,
    offset: 0,
    sort: 'date_requested',
    direction: 'desc',
    status_counts: { all: requests.length, new: 0, accepted: 0, playing: 0, played: 0, rejected: 0 },
    ...overrides,
  };
}

function mockCollectionSettings(phase: 'pre_announce' | 'collection' | 'live' | 'closed' = 'collection') {
  return {
    collection_opens_at: null,
    collection_phase_override: null,
    live_starts_at: null,
    phase,
    submission_cap_per_guest: 15,
    tidal_collection_bidirectional: false,
    tidal_collection_playlist_id: null,
    tidal_sync_enabled: false,
  };
}

function setupDefaultMocks() {
  vi.mocked(api.getEvent).mockResolvedValue(mockEvent());
  vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([]));
  vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.getDisplaySettings).mockResolvedValue({
    status: 'ok', now_playing_hidden: false, now_playing_auto_hide_minutes: 10,
    requests_open: true, kiosk_display_only: false,
  });
  vi.mocked(api.getCollectionSettings).mockReset().mockResolvedValue(mockCollectionSettings());
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
  vi.mocked(api.sendBridgeCommand).mockResolvedValue({
    command_id: 'test',
    command_type: 'ping',
    payload: {},
  });
}


const eventPageTestContext: EventPageTestContext = {
  eventPageTestState, mockPush, api, ApiError, EventQueuePage, mockEvent, deferred, mockRequest,
  mockRequestList, mockCollectionSettings, setupDefaultMocks,
};
describe('EventQueuePage', () => {

  beforeEach(() => {
    vi.clearAllMocks();
    eventPageTestState.mockEventCode = 'TEST';
    eventPageTestState.mockIsAuthenticated = true;
    eventPageTestState.mockIsLoading = false;
    eventPageTestState.mockRole = 'dj';
    eventPageTestState.capturedSongTabProps = {};
    eventPageTestState.capturedManageTabProps = {};
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });


  describe('Initial loading and auth guard', () => {
    it('redirects to /login when not authenticated', () => {
      eventPageTestState.mockIsAuthenticated = false;
      eventPageTestState.mockIsLoading = false;
      setupDefaultMocks();

      render(<EventQueuePage />);

      expect(mockPush).toHaveBeenCalledWith('/login');
    });

    it('redirects pending users to /pending', () => {
      eventPageTestState.mockRole = 'pending';
      setupDefaultMocks();

      render(<EventQueuePage />);

      expect(mockPush).toHaveBeenCalledWith('/pending');
    });

    it('shows Loading while auth is resolving', () => {
      eventPageTestState.mockIsLoading = true;
      eventPageTestState.mockIsAuthenticated = false;
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

  // Regression for baseline 57cfcdc6867f: an old route request could overwrite the event after A→B navigation.
  it('keeps event B when event A finishes after the route changes', async () => {
    vi.mocked(api.getEvent).mockReset();
    setupDefaultMocks();
    const eventA = deferred<Event>();
    vi.mocked(api.getEvent).mockReturnValueOnce(eventA.promise);
    vi.mocked(api.getEvent)
      .mockResolvedValueOnce(
        mockEvent({ code: 'NEXT', join_code: 'NEXTJO', name: 'Event B' }) as Event,
      );

    const view = render(<EventQueuePage />);
    expect(screen.getByText('Loading event...')).toBeInTheDocument();
    eventPageTestState.mockEventCode = 'NEXT';
    view.rerender(<EventQueuePage />);

    await screen.findByText('Event B');
    await act(async () => {
      eventA.resolve(mockEvent({ name: 'Event A' }) as Event);
      await eventA.promise;
    });

    expect(screen.getByText('Event B')).toBeInTheDocument();
    expect(screen.queryByText('Event A')).not.toBeInTheDocument();
  });

  // Regression for baseline 57cfcdc6867f: stale request failure/finally could clear the new route's loading state.
  it('keeps the new route loading when the old route fails, then renders the new event', async () => {
    vi.mocked(api.getEvent).mockReset();
    setupDefaultMocks();
    const eventA = deferred<Event>();
    const eventB = deferred<Event>();
    vi.mocked(api.getEvent)
      .mockReturnValueOnce(eventA.promise)
      .mockReturnValueOnce(eventB.promise);

    const view = render(<EventQueuePage />);
    eventPageTestState.mockEventCode = 'NEXT';
    view.rerender(<EventQueuePage />);
    await waitFor(() => expect(api.getEvent).toHaveBeenCalledWith('NEXT'));
    expect(api.getEvent).toHaveBeenCalledTimes(2);

    await act(async () => {
      eventA.reject(new Error('stale route failed'));
      await eventA.promise.catch(() => undefined);
    });
    expect(screen.getByText('Loading event...')).toBeInTheDocument();

    await act(async () => {
      eventB.resolve(mockEvent({ code: 'NEXT', join_code: 'NEXTJO', name: 'Event B' }) as Event);
      await eventB.promise;
    });
    expect(await screen.findByText('Event B')).toBeInTheDocument();
    expect(screen.queryByTestId('error-card')).not.toBeInTheDocument();
  });

  // Regression for baseline 57cfcdc6867f: changing the route must not start protected requests for pending accounts.
  it('does not load event or provider data for a pending user after the route changes', () => {
    vi.mocked(api.getEvent).mockReset();
    vi.mocked(api.getTidalStatus).mockReset();
    vi.mocked(api.getBeatportStatus).mockReset();
    eventPageTestState.mockRole = 'pending';
    const view = render(<EventQueuePage />);

    eventPageTestState.mockEventCode = 'NEXT';
    view.rerender(<EventQueuePage />);

    expect(api.getEvent).not.toHaveBeenCalled();
    expect(api.getTidalStatus).not.toHaveBeenCalled();
    expect(api.getBeatportStatus).not.toHaveBeenCalled();
  });

  // Regression for baseline 57cfcdc6867f: a delayed archived-event lookup from route A could report its error on route B.
  it('ignores an archived lookup failure after the route changes', async () => {
    vi.mocked(api.getEvent).mockReset();
    setupDefaultMocks();
    const archivedEvents = deferred<Awaited<ReturnType<typeof api.getArchivedEvents>>>();
    vi.mocked(api.getEvent)
      .mockRejectedValueOnce(new ApiError('Expired', 410))
      .mockResolvedValueOnce(mockEvent({ code: 'NEXT', join_code: 'NEXTJO', name: 'Event B' }) as Event);
    vi.mocked(api.getArchivedEvents).mockReturnValueOnce(archivedEvents.promise);

    const view = render(<EventQueuePage />);
    await waitFor(() => expect(api.getArchivedEvents).toHaveBeenCalled());
    eventPageTestState.mockEventCode = 'NEXT';
    view.rerender(<EventQueuePage />);
    expect(await screen.findByText('Event B')).toBeInTheDocument();

    await act(async () => {
      archivedEvents.reject(new Error('Old archived lookup failed'));
      await archivedEvents.promise.catch(() => undefined);
    });
    expect(screen.getByText('Event B')).toBeInTheDocument();
    expect(screen.queryByTestId('error-card')).not.toBeInTheDocument();
  });

  // Regression for baseline 57cfcdc6867f: a previous route's loaded flag hid a new route's initial failure.
  it('does not keep showing event A after event B fails to load', async () => {
    vi.mocked(api.getEvent).mockReset();
    setupDefaultMocks();
    const view = render(<EventQueuePage />);
    await screen.findByText('Test Event');
    eventPageTestState.mockEventCode = 'NEXT';
    vi.mocked(api.getEvent).mockRejectedValueOnce(new Error('Event B unavailable'));
    view.rerender(<EventQueuePage />);

    await waitFor(() => expect(api.getEvent).toHaveBeenCalledWith('NEXT'));
    expect(await screen.findByTestId('error-card')).toBeInTheDocument();
    expect(screen.queryByText('Test Event')).not.toBeInTheDocument();
  });

  // Regression for baseline 57cfcdc6867f: old join-code live data could overwrite the current event's status.
  it('discards event A live-status responses after event B loads', async () => {
    vi.mocked(api.getEvent).mockReset();
    vi.mocked(api.getPlayHistory).mockReset();
    vi.mocked(api.getNowPlaying).mockReset();
    vi.mocked(api.getBridgeStatus).mockReset();
    setupDefaultMocks();
    const historyA = deferred<Awaited<ReturnType<typeof api.getPlayHistory>>>();
    const nowPlayingA = deferred<Awaited<ReturnType<typeof api.getNowPlaying>>>();
    const bridgeA = deferred<Awaited<ReturnType<typeof api.getBridgeStatus>>>();
    vi.mocked(api.getPlayHistory).mockReturnValueOnce(historyA.promise);
    vi.mocked(api.getNowPlaying).mockReturnValueOnce(nowPlayingA.promise);
    vi.mocked(api.getBridgeStatus).mockReturnValueOnce(bridgeA.promise);
    vi.mocked(api.getEvent)
      .mockResolvedValueOnce(mockEvent() as Event)
      .mockResolvedValueOnce(
        mockEvent({ code: 'NEXT', join_code: 'NEXTJO', name: 'Event B' }) as Event,
      );

    const view = render(<EventQueuePage />);
    await screen.findByText('Test Event');
    eventPageTestState.mockEventCode = 'NEXT';
    view.rerender(<EventQueuePage />);
    await screen.findByText('Event B');
    await waitFor(() => expect(api.getBridgeStatus).toHaveBeenCalledWith('NEXTJO'));
    await act(async () => Promise.resolve());

    await act(async () => {
      historyA.resolve({ items: [], total: 0 });
      nowPlayingA.resolve({ title: 'Stale A track' } as Awaited<ReturnType<typeof api.getNowPlaying>>);
      bridgeA.resolve({
        connected: true, device_name: 'A deck', last_seen: null,
        circuit_breaker_state: null, buffer_size: 2, plugin_id: 'a',
        deck_count: 1, uptime_seconds: 10,
      });
      await Promise.all([historyA.promise, nowPlayingA.promise, bridgeA.promise]);
    });

    expect(screen.getByText('Event B')).toBeInTheDocument();
    expect(screen.queryByTestId('now-playing-badge')).not.toBeInTheDocument();
    expect((eventPageTestState.capturedManageTabProps.bridge as { connected: boolean }).connected).toBe(false);
    expect((eventPageTestState.capturedSongTabProps.playHistory as { items: unknown[] }).items).toEqual([]);
  });

    it('renders QR code', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);

      await screen.findByText('Test Event');
      expect(screen.getByTestId('qr-code')).toBeInTheDocument();
    });

    it('renders event join_code under the QR and encodes it in the QR payload', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);

      // The big bold code shown above the "Scan to join" QR is the join_code
      // — that's what the QR encodes. Collection code is the URL slug DJs
      // navigate by but is not the human-facing scan target.
      await waitFor(() => {
        expect(screen.getByText('TSETJO')).toBeInTheDocument();
      });
      // Lock in the QR routing contract: scanning the QR must take guests to
      // /join/{join_code}, not /join/{collection_code}.
      const qr = screen.getByTestId('qr-code');
      expect(qr.getAttribute('data-value')).toContain('/join/TSETJO');
      expect(qr.getAttribute('data-value')).not.toContain('/join/TEST');
    });
  });
  registerPageErrorsAndSettings(eventPageTestContext);
  registerPageActions(eventPageTestContext);
  registerProviderAndDisplay(eventPageTestContext);
  registerRequestList(eventPageTestContext);
});
