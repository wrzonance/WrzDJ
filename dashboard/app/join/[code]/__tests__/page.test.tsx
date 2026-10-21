import { registerSearchAndSubmission } from './page-search-submission.cases';
import { registerVoteTests } from './page-votes.cases';
import { registerFrictionlessTests } from './page-frictionless.cases';
import type { JoinPageTestContext } from './page-test-context';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';

// Use vi.hoisted so mock objects are available before vi.mock factory runs
const { mockApi, MockApiError, MockHumanVerificationRequiredError, nicknameGateRenderSpy, testControls } =
  vi.hoisted(() => {
  class MockApiError extends Error {
    status: number;
    constructor(message: string, status = 0) {
      super(message);
      this.status = status;
    }
  }

  class MockHumanVerificationRequiredError extends MockApiError {
    constructor() {
      super('Human verification required', 403);
      this.name = 'HumanVerificationRequiredError';
    }
  }

  const mockApi = {
    getEvent: vi.fn(),
    getPublicEvent: vi.fn(),
    checkHasRequested: vi.fn(),
    getCollectEvent: vi.fn(),
    getCollectProfile: vi.fn(),
    getPublicRequests: vi.fn(),
    getMyRequests: vi.fn(),
    submitRequest: vi.fn(),
    publicVoteRequest: vi.fn(),
    publicUnvoteRequest: vi.fn(),
    eventSearch: vi.fn(),
    search: vi.fn(),
    getJoinConfig: vi.fn(),
    ensureGuestName: vi.fn(),
  };

  // Tracks every NicknameGate mock render so tests can assert it never even
  // transiently mounted (final-DOM absence alone misses a mount/unmount flash).
  const nicknameGateRenderSpy = vi.fn();
  const testControls = {
    gateAutoCompletes: true,
    eventStreamHandlers: null as null | {
      onRequestCreated?: (data: { request_id: number; title: string; artist: string }) => void;
    },
  };

  return { mockApi, MockApiError, MockHumanVerificationRequiredError, nicknameGateRenderSpy, testControls };
});

vi.mock('next/navigation', () => ({
  useParams: vi.fn(() => ({ code: 'TEST01' })),
}));

vi.mock('@/lib/use-guest-identity', () => ({
  useGuestIdentity: vi.fn(() => ({
    guestId: 1,
    isReturning: false,
    reconcileHint: false,
    isLoading: false,
    refresh: vi.fn().mockResolvedValue(undefined),
  })),
}));

vi.mock('@/components/EmailRecoveryButton', () => ({
  default: () => null,
}));

vi.mock('@/components/EmailRecoveryModal', () => ({
  default: () => null,
}));

vi.mock('@/lib/use-event-stream', () => ({
  useEventStream: vi.fn((_: string | null, handlers: typeof testControls.eventStreamHandlers) => {
    testControls.eventStreamHandlers = handlers;
  }),
}));

vi.mock('@/components/NicknameGate', async () => {
  const { useEffect } = await vi.importActual<typeof import('react')>('react');
  return {
    NicknameGate: ({ onComplete }: { onComplete: (r: unknown) => void }) => {
      nicknameGateRenderSpy();
      useEffect(() => {
        if (testControls.gateAutoCompletes) {
          onComplete({ nickname: 'TestUser', emailVerified: false, submissionCount: 0, submissionCap: 5 });
        }
      }, [onComplete]);
      return (
        <button
          data-testid="nickname-gate"
          onClick={() => onComplete({ nickname: 'TestUser', emailVerified: false, submissionCount: 0, submissionCap: 5 })}
        >
          Complete nickname gate
        </button>
      );
    },
    GateResult: {},
  };
});

vi.mock('@/components/IdentityBar', () => ({
  IdentityBar: ({ nickname }: { nickname: string }) => (
    <div data-testid="identity-bar">{nickname}</div>
  ),
}));

vi.mock('@/lib/api', () => ({
  api: mockApi,
  ApiError: MockApiError,
  HumanVerificationRequiredError: MockHumanVerificationRequiredError,
  PUBLIC_PAGE_MAX: 500,
}));

vi.mock('@/lib/use-human-verification', () => {
  class MockHumanVerificationFailedError extends Error {
    constructor() {
      super('human_verification_failed');
      this.name = 'HumanVerificationFailedError';
    }
  }
  return {
    useHumanVerification: () => ({
      state: 'verified',
      reverify: vi.fn().mockResolvedValue(undefined),
      ensureVerified: vi.fn().mockResolvedValue(undefined),
      retry: vi.fn(),
      widgetContainerRef: { current: null },
    }),
    HumanVerificationFailedError: MockHumanVerificationFailedError,
  };
});

// Import after mocks
import JoinEventPage from '../page';

function setupDefaultMocks() {
  testControls.gateAutoCompletes = true;
  testControls.eventStreamHandlers = null;
  mockApi.eventSearch.mockReset().mockResolvedValue([]);
  mockApi.search.mockReset().mockResolvedValue([]);
  mockApi.getEvent.mockResolvedValue({
    id: 1,
    code: 'TEST01',
    name: 'Test Event',
    requests_open: true,
    banner_url: null,
  });
  mockApi.getPublicEvent.mockResolvedValue({
    name: 'Test Event',
    collection_code: 'TEST01',
    requests_open: true,
    frictionless_join: false,
    phase: 'live',
    submission_cap_per_guest: 5,
    banner_url: null,
    banner_colors: null,
  });
  mockApi.checkHasRequested.mockResolvedValue({ has_requested: false });
  mockApi.getCollectEvent.mockResolvedValue({
    phase: 'live',
    code: 'TEST01',
    name: 'Test Event',
    banner_filename: null,
    banner_url: null,
    banner_colors: null,
    submission_cap_per_guest: 5,
    registration_enabled: false,
    collection_opens_at: null,
    live_starts_at: null,
    expires_at: new Date(Date.now() + 86400000).toISOString(),
  });
  mockApi.getCollectProfile.mockResolvedValue({
    nickname: 'TestUser',
    email_verified: false,
    submission_count: 0,
    submission_cap: 5,
  });
  mockApi.getPublicRequests.mockResolvedValue({ requests: [], now_playing: null });
  mockApi.getMyRequests.mockResolvedValue({ requests: [] });
  // Default: not frictionless, so existing tests still render NicknameGate.
  mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: false });
  mockApi.ensureGuestName.mockResolvedValue({ nickname: 'AutoName', auto_generated: true });
}


const joinPageTestContext: JoinPageTestContext = { JoinEventPage, mockApi, MockApiError, MockHumanVerificationRequiredError, nicknameGateRenderSpy, testControls, setupDefaultMocks };


describe('JoinEventPage — NicknameGate wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  it('renders the gate before any page content loads', async () => {
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Test Event')).toBeInTheDocument();
    });
  });

  it('loads the guest event only after the nickname gate completes', async () => {
    testControls.gateAutoCompletes = false;
    render(<JoinEventPage />);

    await screen.findByTestId('nickname-gate');
    expect(mockApi.getPublicEvent).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Complete nickname gate' }));
    await waitFor(() => expect(mockApi.getPublicEvent).toHaveBeenCalledWith('TEST01'));
  });

  it('shows IdentityBar with gate nickname after gate completes', async () => {
    render(<JoinEventPage />);
    await waitFor(() => {
      const bar = screen.getByTestId('identity-bar');
      expect(bar).toBeInTheDocument();
      expect(bar).toHaveTextContent('TestUser');
    });
  });

  it('loads the event via getPublicEvent and never calls the id-leaking getEvent', async () => {
    setupDefaultMocks();
    render(<JoinEventPage />);
    await waitFor(() => expect(mockApi.getPublicEvent).toHaveBeenCalledWith('TEST01'));
    expect(mockApi.getEvent).not.toHaveBeenCalled();
  });

});

describe('JoinEventPage — error states', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  it('shows Event Expired when API returns 410', async () => {
    mockApi.getPublicEvent.mockRejectedValue(new MockApiError('Gone', 410));
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Event Expired')).toBeInTheDocument();
    });
  });

  it('shows Event Not Found when API returns 404', async () => {
    mockApi.getPublicEvent.mockRejectedValue(new MockApiError('Not found', 404));
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Event Not Found')).toBeInTheDocument();
    });
  });

  it('shows generic error message when API fails with non-HTTP error', async () => {
    mockApi.getPublicEvent.mockRejectedValue(new Error('Network error'));
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Oops!')).toBeInTheDocument();
    });
    expect(screen.getByText('Event not found or has expired.')).toBeInTheDocument();
  });

  it('shows error from ApiError message when status is generic', async () => {
    mockApi.getPublicEvent.mockRejectedValue(new MockApiError('Something went wrong', 500));
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    });
  });
});

describe('JoinEventPage — requests closed state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
    mockApi.getEvent.mockResolvedValue({
      id: 1,
      code: 'TEST01',
      name: 'Closed Event',
      requests_open: false,
      banner_url: null,
    });
    mockApi.getPublicEvent.mockResolvedValue({
      name: 'Closed Event',
      collection_code: 'TEST01',
      requests_open: false,
      frictionless_join: false,
      phase: 'live',
      submission_cap_per_guest: 5,
      banner_url: null,
      banner_colors: null,
    });
  });

  it('shows requests closed message when requests are not open', async () => {
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Requests are closed for this event')).toBeInTheDocument();
    });
    expect(screen.getByText('Closed Event')).toBeInTheDocument();
  });
});

describe('JoinEventPage — request list view', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
    mockApi.checkHasRequested.mockResolvedValue({ has_requested: true });
  });

  it('shows request list when user has already requested', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 1, title: 'Song One', artist: 'Artist One', status: 'new', vote_count: 0, artwork_url: null, nickname: 'TestUser' },
      ],
      now_playing: null,
    });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Song One')).toBeInTheDocument();
    });
    expect(screen.getByText('Artist One')).toBeInTheDocument();
  });

  it('shows "No requests yet" empty state when request list is empty', async () => {
    mockApi.getPublicRequests.mockResolvedValue({ requests: [], now_playing: null });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('No requests yet. Be the first!')).toBeInTheDocument();
    });
  });

  // Regression for baseline 57cfcdc6867f: each request feed tab must show its
  // own source/order while MINE excludes requests from other guests.
  it('filters MINE and preserves recent versus leaderboard order', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 31, title: 'Recent First', artist: 'Band A', status: 'new', vote_count: 2, artwork_url: null, nickname: null },
        { id: 32, title: 'Highest Votes', artist: 'Band B', status: 'new', vote_count: 9, artwork_url: null, nickname: null },
        { id: 33, title: 'My Request', artist: 'Band C', status: 'new', vote_count: 4, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    mockApi.getMyRequests.mockResolvedValue({ requests: [{ id: 33 }] });
    const { container } = render(<JoinEventPage />);

    await screen.findByText('Recent First');
    await waitFor(() => expect(container.querySelectorAll('.gst-tower-row')).toHaveLength(3));
    const feedTitles = () => Array.from(container.querySelectorAll('.gst-tower-row'))
      .map((row) => row.textContent ?? '');

    // LEADERBOARD sorts the returned rows by vote count, descending.
    expect(feedTitles()[0]).toContain('Highest Votes');
    expect(feedTitles()[1]).toContain('My Request');

    // The API's recent order is retained on RECENT.
    fireEvent.click(screen.getByRole('button', { name: 'RECENT' }));
    expect(feedTitles()[0]).toContain('Recent First');
    expect(feedTitles()[1]).toContain('Highest Votes');

    // MINE keeps only the current guest's request.
    fireEvent.click(screen.getByRole('button', { name: 'MINE' }));
    await waitFor(() => expect(container.querySelectorAll('.gst-tower-row')).toHaveLength(1));
    expect(feedTitles()[0]).toContain('My Request');
    expect(screen.queryByText('Recent First')).not.toBeInTheDocument();
    expect(screen.queryByText('Highest Votes')).not.toBeInTheDocument();
  });

  it('shows the empty-MINE state when the guest has no requests', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 41, title: 'Another Guest Request', artist: 'Band', status: 'new', vote_count: 1, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    mockApi.getMyRequests.mockResolvedValue({ requests: [] });
    render(<JoinEventPage />);

    await screen.findByText('Another Guest Request');
    fireEvent.click(screen.getByRole('button', { name: 'MINE' }));

    expect(await screen.findByText('No requests from you yet.')).toBeInTheDocument();
    expect(screen.queryByText('Another Guest Request')).not.toBeInTheDocument();
  });

  it('shows now playing section when now_playing is provided', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [],
      now_playing: {
        title: 'Playing Song',
        artist: 'Playing Artist',
        album_art_url: null,
      },
    });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Now Playing')).toBeInTheDocument();
      expect(screen.getByText('Playing Song')).toBeInTheDocument();
    });
  });

  it('refreshes the request list when the event stream reports a new request', async () => {
    mockApi.getPublicRequests
      .mockResolvedValueOnce({
        requests: [
          { id: 20, title: 'First Song', artist: 'Band', status: 'new', vote_count: 0, artwork_url: null, nickname: null },
        ],
        now_playing: null,
      })
      .mockResolvedValueOnce({
        requests: [
          { id: 20, title: 'First Song', artist: 'Band', status: 'new', vote_count: 0, artwork_url: null, nickname: null },
          { id: 21, title: 'New Song', artist: 'Other Band', status: 'new', vote_count: 0, artwork_url: null, nickname: null },
        ],
        now_playing: null,
      });

    render(<JoinEventPage />);
    await screen.findByText('First Song');

    act(() => {
      testControls.eventStreamHandlers?.onRequestCreated?.({
        request_id: 21,
        title: 'New Song',
        artist: 'Other Band',
      });
    });

    expect(await screen.findByText('New Song')).toBeInTheDocument();
    expect(mockApi.getPublicRequests).toHaveBeenCalledTimes(2);
  });

  it('shows now playing with artwork when album_art_url is provided', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [],
      now_playing: {
        title: 'Playing Song',
        artist: 'Playing Artist',
        album_art_url: 'https://example.com/art.jpg',
      },
    });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Now Playing')).toBeInTheDocument();
    });
  });

  it('shows "Requests are closed" sticky bar when requests_open is false', async () => {
    mockApi.getEvent.mockResolvedValue({
      id: 1,
      code: 'TEST01',
      name: 'Test Event',
      requests_open: false,
      banner_url: null,
    });
    mockApi.getPublicEvent.mockResolvedValue({
      name: 'Test Event',
      collection_code: 'TEST01',
      requests_open: false,
      frictionless_join: false,
      phase: 'live',
      submission_cap_per_guest: 5,
      banner_url: null,
      banner_colors: null,
    });
    mockApi.getPublicRequests.mockResolvedValue({ requests: [], now_playing: null });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Requests are closed for this event')).toBeInTheDocument();
    });
  });

  it('shows "Request a Song" button when requests are open', async () => {
    mockApi.getPublicRequests.mockResolvedValue({ requests: [], now_playing: null });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /request a song/i })).toBeInTheDocument();
    });
  });

  it('request shows accepted badge when status is accepted', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 2, title: 'Accepted Song', artist: 'The Band', status: 'accepted', vote_count: 3, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Accepted')).toBeInTheDocument();
    });
  });

  it('request shows artwork when artwork_url is provided', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 3, title: 'Art Song', artist: 'Art Band', status: 'new', vote_count: 1, artwork_url: 'https://example.com/art.jpg', nickname: null },
      ],
      now_playing: null,
    });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByAltText('Art Song')).toBeInTheDocument();
    });
  });

  it('clicking "Request a Song" resets form and goes back to search', async () => {
    mockApi.getPublicRequests.mockResolvedValue({ requests: [], now_playing: null });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /request a song/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button', { name: /request a song/i }));
    await waitFor(() => {
      expect(screen.getByText('Request a song')).toBeInTheDocument();
    });
  });

  it('shows pre-event banner when collectPhase is collection', async () => {
    mockApi.getPublicEvent.mockResolvedValue({
      name: 'Test Event',
      collection_code: 'TEST01',
      requests_open: true,
      frictionless_join: false,
      phase: 'collection',
      submission_cap_per_guest: 5,
      banner_url: null,
      banner_colors: null,
    });
    mockApi.getPublicRequests.mockResolvedValue({ requests: [], now_playing: null });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText(/pre-event voting is open/i)).toBeInTheDocument();
    });
  });

  it('shows pre-event banner when collectPhase is pre_announce', async () => {
    mockApi.getPublicEvent.mockResolvedValue({
      name: 'Test Event',
      collection_code: 'TEST01',
      requests_open: true,
      frictionless_join: false,
      phase: 'pre_announce',
      submission_cap_per_guest: 5,
      banner_url: null,
      banner_colors: null,
    });
    mockApi.getPublicRequests.mockResolvedValue({ requests: [], now_playing: null });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText(/pre-event voting is open/i)).toBeInTheDocument();
    });
  });

  it('shows request nickname when provided', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 4, title: 'Song', artist: 'Band', status: 'new', vote_count: 0, artwork_url: null, nickname: 'RequestUser' },
      ],
      now_playing: null,
    });
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Requested by RequestUser')).toBeInTheDocument();
    });
  });
});
registerSearchAndSubmission(joinPageTestContext);
registerVoteTests(joinPageTestContext);
registerFrictionlessTests(joinPageTestContext);
