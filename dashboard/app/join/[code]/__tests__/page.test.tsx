import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

// Use vi.hoisted so mock objects are available before vi.mock factory runs
const { mockApi, MockApiError } = vi.hoisted(() => {
  class MockApiError extends Error {
    status: number;
    constructor(message: string, status = 0) {
      super(message);
      this.status = status;
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
    eventSearch: vi.fn(),
    search: vi.fn(),
    getJoinConfig: vi.fn(),
    ensureGuestName: vi.fn(),
  };

  return { mockApi, MockApiError };
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
  useEventStream: vi.fn(),
}));

vi.mock('@/components/NicknameGate', () => ({
  NicknameGate: ({ onComplete }: { onComplete: (r: unknown) => void }) => {
    onComplete({ nickname: 'TestUser', emailVerified: false, submissionCount: 0, submissionCap: 5 });
    return null;
  },
  GateResult: {},
}));

vi.mock('@/components/IdentityBar', () => ({
  IdentityBar: ({ nickname }: { nickname: string }) => (
    <div data-testid="identity-bar">{nickname}</div>
  ),
}));

vi.mock('@/lib/api', () => ({
  api: mockApi,
  ApiError: MockApiError,
}));

vi.mock('@/lib/useHumanVerification', () => ({
  useHumanVerification: () => ({
    state: 'verified',
    reverify: vi.fn().mockResolvedValue(undefined),
    ensureVerified: vi.fn().mockResolvedValue(undefined),
    widgetContainerRef: { current: null },
  }),
}));

// Import after mocks
import JoinEventPage from '../page';

function setupDefaultMocks() {
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

describe('JoinEventPage — search and submission flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  it('shows search form after gate completes', async () => {
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search for a song/i)).toBeInTheDocument();
    });
  });

  it('shows search results after successful search', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Found Song', artist: 'Found Artist', popularity: 80, source: 'spotify', url: 'spotify://track/1', album_art: null, album: null, spotify_id: '1', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Found' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('Found Song')).toBeInTheDocument();
    });
  });

  it('falls back to generic search when event search fails', async () => {
    mockApi.eventSearch.mockRejectedValue(new Error('Not found'));
    mockApi.search.mockResolvedValue([
      { title: 'Generic Song', artist: 'Generic Artist', popularity: 50, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '2', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Generic' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('Generic Song')).toBeInTheDocument();
    });
  });

  it('does not search when query is empty', async () => {
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    expect(mockApi.eventSearch).not.toHaveBeenCalled();
  });

  it('shows confirm request page when song is selected', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Select Me', artist: 'Pick Band', popularity: 70, source: 'spotify', url: null, album_art: null, album: 'My Album', spotify_id: '3', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Select' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => screen.getByText('Select Me'));
    fireEvent.click(screen.getByText('Select Me'));

    await waitFor(() => {
      expect(screen.getByText('Confirm Request')).toBeInTheDocument();
      expect(screen.getByText('Select Me')).toBeInTheDocument();
    });
  });

  it('shows beatport icon for beatport source results', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'BP Track', artist: 'BP Artist', popularity: 90, source: 'beatport', url: 'https://beatport.com/track/1', album_art: null, album: null, spotify_id: null, genre: 'Techno', bpm: 130, key: '4A' },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'BP' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('BP Track')).toBeInTheDocument();
      expect(screen.getByTitle('Beatport')).toBeInTheDocument();
    });
  });

  it('shows album art in search result when provided', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Art Song', artist: 'Art Band', popularity: 60, source: 'spotify', url: null, album_art: 'https://example.com/cover.jpg', album: 'Great Album', spotify_id: '4', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Art' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByAltText('Great Album')).toBeInTheDocument();
    });
  });

  it('back button from confirm screen goes back to search results', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Back Song', artist: 'Back Band', popularity: 50, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '5', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Back' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Back Song'));
    fireEvent.click(screen.getByText('Back Song'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /back/i }));

    await waitFor(() => {
      expect(screen.getByText('Back Song')).toBeInTheDocument();
    });
  });

  it('submits request and shows success state', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Submit Me', artist: 'Submit Band', popularity: 75, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '6', genre: null, bpm: null, key: null },
    ]);
    mockApi.submitRequest.mockResolvedValue({ id: 100, is_duplicate: false, vote_count: 1 });

    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Submit' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Submit Me'));
    fireEvent.click(screen.getByText('Submit Me'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() => {
      expect(screen.getByText('Request Submitted!')).toBeInTheDocument();
    });
  });

  it('shows "Vote Added!" when submission is a duplicate', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Dupe Song', artist: 'Dupe Band', popularity: 60, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '7', genre: null, bpm: null, key: null },
    ]);
    mockApi.submitRequest.mockResolvedValue({ id: 101, is_duplicate: true, vote_count: 5 });

    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Dupe' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Dupe Song'));
    fireEvent.click(screen.getByText('Dupe Song'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() => {
      expect(screen.getByText('Vote Added!')).toBeInTheDocument();
    });
  });

  it('shows error when submission fails with generic error', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Error Song', artist: 'Error Band', popularity: 55, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '8', genre: null, bpm: null, key: null },
    ]);
    mockApi.submitRequest.mockRejectedValue(new Error('Server fail'));

    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Error' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Error Song'));
    fireEvent.click(screen.getByText('Error Song'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() => {
      expect(screen.getByText('Failed to submit request. Please try again.')).toBeInTheDocument();
    });
  });

  it('closes requests when submission returns 403', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Locked Song', artist: 'Locked Band', popularity: 40, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '9', genre: null, bpm: null, key: null },
    ]);
    mockApi.submitRequest.mockRejectedValue(new MockApiError('Forbidden', 403));

    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Locked' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Locked Song'));
    fireEvent.click(screen.getByText('Locked Song'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() => {
      // After 403, goes back to search — request closed for this event
      expect(screen.getByText('Requests are closed for this event')).toBeInTheDocument();
    });
  });

  it('shows album art on confirm request screen when present', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Art Confirm', artist: 'Art Confirm Band', popularity: 65, source: 'spotify', url: null, album_art: 'https://example.com/art2.jpg', album: 'Art Album', spotify_id: '10', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Art' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Art Confirm'));
    fireEvent.click(screen.getByText('Art Confirm'));

    await waitFor(() => {
      const img = screen.getByAltText('Art Album');
      expect(img).toHaveAttribute('src', 'https://example.com/art2.jpg');
    });
  });
});

describe('JoinEventPage — vote flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
    mockApi.checkHasRequested.mockResolvedValue({ has_requested: true });
  });

  it('votes on a request and updates vote count', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 10, title: 'Vote Song', artist: 'Vote Band', status: 'new', vote_count: 2, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    mockApi.publicVoteRequest.mockResolvedValue({ vote_count: 3 });

    render(<JoinEventPage />);
    await waitFor(() => screen.getByText('Vote Song'));

    // Vote button has ▲ symbol (▲ = &#9650; = ▲) — find the button in the request item
    const voteBtn = screen.getAllByRole('button').find((btn) =>
      btn.textContent?.includes('▲') || btn.textContent?.includes('2')
    );
    expect(voteBtn).toBeTruthy();
    fireEvent.click(voteBtn!);

    await waitFor(() => {
      expect(mockApi.publicVoteRequest).toHaveBeenCalledWith(10, expect.any(Function));
    });
  });

  it('handles already-voted error gracefully (marks as voted locally)', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 11, title: 'Already Voted', artist: 'Band', status: 'new', vote_count: 1, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    mockApi.publicVoteRequest.mockRejectedValue(new MockApiError('Already voted', 400));

    render(<JoinEventPage />);
    await waitFor(() => screen.getByText('Already Voted'));

    const voteBtn = screen.getAllByRole('button').find((btn) =>
      btn.textContent?.includes('▲') || btn.textContent?.includes('1')
    );
    expect(voteBtn).toBeTruthy();
    fireEvent.click(voteBtn!);

    await waitFor(() => {
      expect(mockApi.publicVoteRequest).toHaveBeenCalled();
    });
  });

  it('handles rate limited vote gracefully', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 12, title: 'Rate Limited Song', artist: 'Band', status: 'new', vote_count: 0, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    mockApi.publicVoteRequest.mockRejectedValue(new MockApiError('Rate limit', 429));

    render(<JoinEventPage />);
    await waitFor(() => screen.getByText('Rate Limited Song'));

    // The vote button shows ▲ symbol with no count (vote_count is 0)
    const voteBtn = screen.getAllByRole('button').find((btn) =>
      btn.closest('.guest-request-item') !== null
    );
    expect(voteBtn).toBeTruthy();
    fireEvent.click(voteBtn!);

    await waitFor(() => {
      expect(mockApi.publicVoteRequest).toHaveBeenCalled();
    });
  });
});

describe('JoinEventPage — frictionless join', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  it('skips NicknameGate and auto-names when frictionless_join is on', async () => {
    mockApi.getJoinConfig.mockResolvedValue({ frictionless_join: true });
    mockApi.ensureGuestName.mockResolvedValue({ nickname: 'DancingPanda', auto_generated: true });
    mockApi.getEvent.mockResolvedValue({
      id: 1, code: 'TEST01', join_code: 'TEST01', name: 'Party', requests_open: true,
      frictionless_join: true,
    } as never);
    mockApi.getPublicEvent.mockResolvedValue({
      name: 'Party',
      collection_code: 'TEST01',
      requests_open: true,
      frictionless_join: true,
      phase: 'live',
      submission_cap_per_guest: 5,
      banner_url: null,
      banner_colors: null,
    });
    mockApi.checkHasRequested.mockResolvedValue({ has_requested: false } as never);
    render(<JoinEventPage />);
    // No "What's your nickname?" gate; the auto-name shows in the identity bar.
    await waitFor(() => expect(screen.getByText(/DancingPanda/)).toBeInTheDocument());
    expect(screen.queryByText(/What's your nickname/i)).not.toBeInTheDocument();
  });
});

describe('JoinEventPage — checkHasRequested failure', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
    mockApi.checkHasRequested.mockRejectedValue(new Error('Network error'));
  });

  it('falls back gracefully when checkHasRequested fails', async () => {
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByText('Test Event')).toBeInTheDocument();
    });
    expect(screen.getByPlaceholderText(/search for a song/i)).toBeInTheDocument();
  });
});
