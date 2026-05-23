import { render, screen, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import KioskDisplayPage from './page';

// Mock next/navigation
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useParams: () => ({ code: 'TEST123' }),
  useRouter: () => ({ push: mockPush }),
}));

// Mock qrcode.react
vi.mock('qrcode.react', () => ({
  QRCodeSVG: ({ value }: { value: string }) => (
    <div data-testid="qr-code" data-value={value}>QR Code</div>
  ),
}));

// Mock localStorage
const localStorageStore: Record<string, string> = {};
const localStorageMock = {
  getItem: (key: string) => localStorageStore[key] ?? null,
  setItem: (key: string, value: string) => { localStorageStore[key] = value; },
  removeItem: (key: string) => { delete localStorageStore[key]; },
  clear: () => { for (const key of Object.keys(localStorageStore)) delete localStorageStore[key]; },
};
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, writable: true, configurable: true });

// Mock SSE hook
vi.mock('@/lib/use-event-stream', () => ({
  useEventStream: () => ({ connected: false }),
}));

// Mock RequestModal
vi.mock('./components/RequestModal', () => ({
  RequestModal: () => <div data-testid="request-modal">Modal</div>,
}));

// Mock API responses
const mockKioskDisplay = {
  event: { code: 'TEST123', name: 'Test Event' },
  qr_join_url: 'https://example.com/join/TEST123',
  accepted_queue: [
    { id: 1, title: 'Song 1', artist: 'Artist 1', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
    { id: 2, title: 'Song 2', artist: 'Artist 2', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
  ],
  now_playing: null,
  now_playing_hidden: false,
  requests_open: true,
  updated_at: new Date().toISOString(),
  banner_url: null,
  banner_kiosk_url: null,
  banner_colors: null,
  kiosk_display_only: false,
};

const mockNowPlaying = {
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

const mockPlayHistory = {
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
}));

import { api, ApiError } from '@/lib/api';

function setupDefaultMocks() {
  vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
  vi.mocked(api.getNowPlaying).mockResolvedValue(null);
  vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });
}

describe('KioskDisplayPage', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorageMock.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('Three-column layout', () => {
    it('renders 3 columns when now-playing exists', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue(mockPlayHistory);

      render(<KioskDisplayPage />);

      // Wait for loading to finish
      await screen.findByText('Test Event');

      // All three sections should be present
      expect(screen.getByText(/now playing/i)).toBeInTheDocument();
      expect(document.querySelector('.kiosk-panel-label')).toBeInTheDocument();
      expect(screen.getByText(/recently played/i)).toBeInTheDocument();

      // Now playing content should show
      expect(screen.getByText('Currently Playing Song')).toBeInTheDocument();
      expect(screen.getByText('Current Artist')).toBeInTheDocument();
    });

    it('renders 2 columns when no now-playing (queue + history only)', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue(mockPlayHistory);

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      // Now Playing section should NOT be present (only in panel label)
      expect(screen.queryByText(/now playing/i)).not.toBeInTheDocument();

      // Queue and history should still be present
      const panelLabels = document.querySelectorAll('.kiosk-panel-label');
      expect(panelLabels.length).toBeGreaterThanOrEqual(2);
      expect(screen.getByText(/recently played/i)).toBeInTheDocument();
    });

    it('shows history section as a separate column, not nested in queue', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue(mockPlayHistory);

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      // Find the queue panel (has the queue-header inside it)
      const queueHeader = document.querySelector('.queue-header');
      const queuePanel = queueHeader?.closest('.kiosk-panel');
      const historyLabel = screen.getByText(/recently played/i);
      const historyPanel = historyLabel.closest('.kiosk-panel');

      // History section should NOT be inside queue section
      expect(queuePanel).not.toContainElement(historyPanel as HTMLElement);

      // Both should be direct children of kiosk-main
      expect(queuePanel?.parentElement?.classList.contains('kiosk-main')).toBe(true);
      expect(historyPanel?.parentElement?.classList.contains('kiosk-main')).toBe(true);
    });

    it('displays accepted requests in the queue section', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue(mockPlayHistory);

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      // Queue items should be displayed
      expect(screen.getByText('Song 1')).toBeInTheDocument();
      expect(screen.getByText('Artist 1')).toBeInTheDocument();
      expect(screen.getByText('Song 2')).toBeInTheDocument();
      expect(screen.getByText('Artist 2')).toBeInTheDocument();
    });

    it('displays play history in the history section', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue(mockPlayHistory);

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      // History items should be displayed
      expect(screen.getByText('History Song 1')).toBeInTheDocument();
      expect(screen.getByText('History Artist 1')).toBeInTheDocument();
      expect(screen.getByText('History Song 2')).toBeInTheDocument();
    });

    it('shows "Requested" badge for history items that were requests', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue(mockPlayHistory);

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      // One history item has matched_request_id, should show badge
      expect(screen.getByText('Requested')).toBeInTheDocument();
    });
  });

  describe('Requests open/closed', () => {
    it('shows request button when requests_open is true', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        requests_open: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(screen.getByRole('button', { name: /request a song/i })).toBeInTheDocument();
      expect(screen.queryByText('Requests Closed')).not.toBeInTheDocument();
    });

    it('shows closed status when requests_open is false', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        requests_open: false,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(screen.getByText('Requests Closed')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /request a song/i })).not.toBeInTheDocument();
    });

    it('hides request button in display-only mode', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        kiosk_display_only: true,
        requests_open: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(screen.queryByRole('button', { name: /request a song/i })).not.toBeInTheDocument();
    });
  });

  describe('Transient error resilience', () => {
    it('preserves display state when API call fails transiently', async () => {
      // Persistent success mock — ensures interval polls always have a fallback
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      // Wait for initial load
      await screen.findByText('Test Event');
      expect(screen.getByText('Song 1')).toBeInTheDocument();

      // Queue a one-shot failure; the persistent mockResolvedValue still handles subsequent polls
      vi.mocked(api.getKioskDisplay).mockRejectedValueOnce(new Error('Network error'));

      // The existing display data should still be visible (not replaced with error)
      await vi.waitFor(() => {
        expect(screen.getByText('Test Event')).toBeInTheDocument();
        expect(screen.getByText('Song 1')).toBeInTheDocument();
      });
    });
  });

  describe('Empty states', () => {
    it('shows empty queue message when no accepted requests', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue: [],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue(mockPlayHistory);

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(screen.getByText('No songs in queue yet.')).toBeInTheDocument();
    });

    it('still shows history section when history is empty', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      // History section should still be present (for 3-column layout consistency)
      expect(screen.getByText(/recently played/i)).toBeInTheDocument();
    });

    it('shows empty history message', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(screen.getByText('No songs played yet.')).toBeInTheDocument();
    });
  });

  describe('10s polling loop (SSE handles real-time)', () => {
    it('calls loadDisplay on mount', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(api.getKioskDisplay).toHaveBeenCalledTimes(1);
    });

    it('polls every 10 seconds', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();

      render(<KioskDisplayPage />);
      // Flush initial load
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      expect(api.getKioskDisplay).toHaveBeenCalledTimes(1);

      // Advance 10s — second poll
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(2);

      // Advance 10s more — third poll
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(3);
    });

    it('stops polling on 404', async () => {
      vi.useFakeTimers();
      vi.mocked(api.getKioskDisplay).mockRejectedValue(new ApiError('Not found', 404));
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      const callCount = vi.mocked(api.getKioskDisplay).mock.calls.length;

      // Advance past several poll intervals — no more calls
      await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(callCount);
    });

    it('stops polling on 410', async () => {
      vi.useFakeTimers();
      vi.mocked(api.getKioskDisplay).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      const callCount = vi.mocked(api.getKioskDisplay).mock.calls.length;

      await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(callCount);
    });

    it('continues polling on transient error', async () => {
      vi.useFakeTimers();
      vi.mocked(api.getKioskDisplay)
        .mockResolvedValueOnce(mockKioskDisplay) // initial
        .mockRejectedValueOnce(new Error('Transient')) // 1st poll
        .mockResolvedValue(mockKioskDisplay); // subsequent
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(1);

      // Error on second call
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(2);

      // Should still poll after error
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(3);
    });
  });

  describe('Sticky now-playing (10s grace)', () => {
    it('shows now-playing immediately', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Currently Playing Song');
      expect(screen.getByText('Current Artist')).toBeInTheDocument();
    });

    it('shows LIVE badge for bridge sources', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Currently Playing Song');
      expect(screen.getByText('LIVE')).toBeInTheDocument();
    });

    it('does not show LIVE badge for manual source', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue({
        ...mockNowPlaying,
        source: 'manual',
      });
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Currently Playing Song');
      expect(screen.queryByText('LIVE')).not.toBeInTheDocument();
    });

    it('keeps track visible during 10s grace period after null', async () => {
      vi.useFakeTimers();
      // Initial: has now playing
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(screen.getByText('Currently Playing Song')).toBeInTheDocument();

      // Now playing goes null on next poll
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

      // Track should still be visible during grace period
      expect(screen.getByText('Currently Playing Song')).toBeInTheDocument();

      // Should have fading class
      const section = screen.getByText(/now playing/i).closest('.now-playing-section');
      expect(section?.classList.contains('fading')).toBe(true);
    });

    it('clears track after 10s grace period', async () => {
      vi.useFakeTimers();
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(screen.getByText('Currently Playing Song')).toBeInTheDocument();

      // Now playing goes null
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

      // Advance past the 10s grace
      await act(async () => { await vi.advanceTimersByTimeAsync(11000); });

      expect(screen.queryByText('Currently Playing Song')).not.toBeInTheDocument();
      expect(screen.queryByText(/now playing/i)).not.toBeInTheDocument();
    });

    it('cancels grace timer when new track arrives', async () => {
      vi.useFakeTimers();
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Now playing goes null — starts grace period
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

      // New track arrives within grace period
      const newTrack = { ...mockNowPlaying, title: 'New Track', artist: 'New Artist' };
      vi.mocked(api.getNowPlaying).mockResolvedValue(newTrack);
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

      expect(screen.getByText('New Track')).toBeInTheDocument();
      expect(screen.getByText('New Artist')).toBeInTheDocument();

      // Should not be fading
      const section = screen.getByText(/now playing/i).closest('.now-playing-section');
      expect(section?.classList.contains('fading')).toBe(false);
    });
  });

  describe('New item animation', () => {
    it('adds queue-item-new class for new items', async () => {
      vi.useFakeTimers();
      // Initial: 1 item
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue: [{ id: 1, title: 'Song 1', artist: 'Artist 1', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false }],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Second poll adds a new item
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue: [
          { id: 1, title: 'Song 1', artist: 'Artist 1', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
          { id: 3, title: 'Song 3', artist: 'Artist 3', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
        ],
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

      const newItem = screen.getByText('Song 3').closest('.queue-item');
      expect(newItem?.classList.contains('queue-item-new')).toBe(true);
    });

    it('removes animation class after 800ms', async () => {
      vi.useFakeTimers();
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue: [{ id: 1, title: 'Song 1', artist: 'Artist 1', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false }],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Add new item
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue: [
          { id: 1, title: 'Song 1', artist: 'Artist 1', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
          { id: 3, title: 'Song 3', artist: 'Artist 3', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
        ],
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

      // Verify animation class is present
      let newItem = screen.getByText('Song 3').closest('.queue-item');
      expect(newItem?.classList.contains('queue-item-new')).toBe(true);

      // Advance 800ms for animation timeout
      await act(async () => { await vi.advanceTimersByTimeAsync(800); });

      newItem = screen.getByText('Song 3').closest('.queue-item');
      expect(newItem?.classList.contains('queue-item-new')).toBe(false);
    });
  });

  describe('Vote badges', () => {
    it('shows vote count for items with votes', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue: [
          { id: 1, title: 'Popular Song', artist: 'Artist', artwork_url: null, nickname: null, vote_count: 5, bpm: null, musical_key: null, genre: null, requester_verified: false },
        ],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Popular Song');
      const voteNum = document.querySelector('.queue-item-vote-num');
      expect(voteNum?.textContent).toBe('5');
    });

    it('shows vote count of 1', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue: [
          { id: 1, title: 'Song', artist: 'Artist', artwork_url: null, nickname: null, vote_count: 1, bpm: null, musical_key: null, genre: null, requester_verified: false },
        ],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Song');
      const voteNum = document.querySelector('.queue-item-vote-num');
      expect(voteNum?.textContent).toBe('1');
    });

    it('shows zero for items with no votes', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue: [
          { id: 1, title: 'Song', artist: 'Artist', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
        ],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Song');
      const voteNum = document.querySelector('.queue-item-vote-num');
      expect(voteNum?.textContent).toBe('0');
    });
  });

  describe('Kiosk protections', () => {
    it('prevents context menu', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);
      await screen.findByText('Test Event');

      const event = new Event('contextmenu', { cancelable: true });
      const prevented = !document.dispatchEvent(event);
      expect(prevented).toBe(true);
    });

    it('prevents text selection', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);
      await screen.findByText('Test Event');

      const event = new Event('selectstart', { cancelable: true });
      const prevented = !document.dispatchEvent(event);
      expect(prevented).toBe(true);
    });
  });

  describe('Banner', () => {
    it('applies banner gradient with valid colors', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        banner_colors: ['#1a2b3c', '#4d5e6f', '#7a8b9c'],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const container = screen.getByText('Test Event').closest('.kiosk-container') as HTMLElement;
      const bgStyle = container?.style.getPropertyValue('--kiosk-bg');
      expect(bgStyle).toContain('#1a2b3c');
      expect(bgStyle).toContain('#4d5e6f');
      expect(bgStyle).toContain('#7a8b9c');
    });

    it('falls back for invalid color values', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        banner_colors: ['bad', '#4d5e6f', 'nope'],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const container = screen.getByText('Test Event').closest('.kiosk-container') as HTMLElement;
      const bgStyle = container?.style.getPropertyValue('--kiosk-bg');
      // Should use fallback for invalid colors
      expect(bgStyle).toContain('#1a1a2e'); // fallback for first
      expect(bgStyle).toContain('#4d5e6f'); // valid
      expect(bgStyle).toContain('#0f3460'); // fallback for third
    });

    it('renders banner image when present', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        banner_kiosk_url: '/uploads/banners/test-kiosk.webp',
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const bannerBg = document.querySelector('.kiosk-banner-bg img') as HTMLImageElement;
      expect(bannerBg).toBeInTheDocument();
      expect(bannerBg.src).toContain('/uploads/banners/test-kiosk.webp');
    });

    it('does not render banner when no banner_kiosk_url', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(document.querySelector('.kiosk-banner-bg')).not.toBeInTheDocument();
    });

    it('hides banner container on image load error', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        banner_kiosk_url: '/uploads/banners/missing-kiosk.webp',
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const bannerImg = document.querySelector('.kiosk-banner-bg img') as HTMLImageElement;
      expect(bannerImg).toBeInTheDocument();

      // Simulate image load error
      await act(async () => {
        bannerImg.dispatchEvent(new Event('error'));
      });

      // Parent container should be hidden
      const bannerBg = document.querySelector('.kiosk-banner-bg') as HTMLElement;
      expect(bannerBg.style.display).toBe('none');
    });
  });

  describe('Kiosk-specific styling', () => {
    it('shows plus icon on request button', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const button = screen.getByRole('button', { name: /request a song/i });
      expect(button.querySelector('svg')).toBeInTheDocument();
    });

    it('applies cursor:none to global styles', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      // Check that the global style tag contains cursor: none
      const styleTags = document.querySelectorAll('style');
      const hasNoCursor = Array.from(styleTags).some(
        (tag) => tag.textContent?.includes('cursor: none') || tag.textContent?.includes('cursor:none')
      );
      expect(hasNoCursor).toBe(true);
    });
  });

  describe('Error display', () => {
    it('shows "Event Expired" for 410', async () => {
      vi.mocked(api.getKioskDisplay).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Event Expired');
      expect(screen.getByText(/no longer accepting requests/i)).toBeInTheDocument();
    });

    it('shows "Event Not Found" for 404', async () => {
      vi.mocked(api.getKioskDisplay).mockRejectedValue(new ApiError('Not found', 404));
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Event Not Found');
      expect(screen.getByText(/does not exist/i)).toBeInTheDocument();
    });

    it('shows generic error for non-API errors on initial load', async () => {
      vi.mocked(api.getKioskDisplay).mockRejectedValue(new Error('Network'));
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Error');
    });
  });

  describe('Loading state', () => {
    it('shows Loading while data is being fetched', () => {
      vi.mocked(api.getKioskDisplay).mockImplementation(
        () => new Promise(() => {}), // never resolves
      );
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });
  });

  describe('Now playing from request fallback', () => {
    it('shows request-based now_playing when no bridge now-playing', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        now_playing: { id: 1, title: 'Request Song', artist: 'Request Artist', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Request Song');
      expect(screen.getByText('Request Artist')).toBeInTheDocument();
      // Should not show LIVE badge for request-based
      expect(screen.queryByText('LIVE')).not.toBeInTheDocument();
    });

    it('hides now-playing when now_playing_hidden is true', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        now_playing: { id: 1, title: 'Hidden Song', artist: 'Hidden Artist', artwork_url: null, nickname: null, vote_count: 0, bpm: null, musical_key: null, genre: null, requester_verified: false },
        now_playing_hidden: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(screen.queryByText('Hidden Song')).not.toBeInTheDocument();
      expect(screen.queryByText(/now playing/i)).not.toBeInTheDocument();
    });
  });

  describe('Kiosk session unpair detection', () => {
    it('redirects to /kiosk-pair on 404 (unpaired)', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      localStorageMock.setItem('kiosk_session_token', 'test-session-token');
      localStorageMock.setItem('kiosk_pair_code', 'ABC123');
      vi.mocked(api.getKioskAssignment).mockRejectedValue(new ApiError('Not found', 404));

      render(<KioskDisplayPage />);
      // Flush initial load
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Advance past 10s session check interval
      await act(async () => { await vi.advanceTimersByTimeAsync(10000); });

      expect(mockPush).toHaveBeenCalledWith('/kiosk-pair');
      expect(localStorageMock.getItem('kiosk_session_token')).toBeNull();
      expect(localStorageMock.getItem('kiosk_pair_code')).toBeNull();
    });

    it('does NOT redirect when session is valid', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      localStorageMock.setItem('kiosk_session_token', 'test-session-token');
      vi.mocked(api.getKioskAssignment).mockResolvedValue({
        status: 'active',
        event_code: 'TEST123',
        event_join_code: 'JOIN78',
        event_name: 'Test Event',
      });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Advance past session check
      await act(async () => { await vi.advanceTimersByTimeAsync(10000); });

      expect(mockPush).not.toHaveBeenCalled();
    });

    it('skips session check when no token in localStorage', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      // No localStorage token set

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Advance past several check intervals
      await act(async () => { await vi.advanceTimersByTimeAsync(30000); });

      expect(api.getKioskAssignment).not.toHaveBeenCalled();
      expect(mockPush).not.toHaveBeenCalled();
    });

    it('ignores transient errors (non-404)', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      localStorageMock.setItem('kiosk_session_token', 'test-session-token');
      vi.mocked(api.getKioskAssignment).mockRejectedValue(new ApiError('Server error', 500));

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      await act(async () => { await vi.advanceTimersByTimeAsync(10000); });

      expect(mockPush).not.toHaveBeenCalled();
      // Token should still be in localStorage
      expect(localStorageMock.getItem('kiosk_session_token')).toBe('test-session-token');
    });
  });

  describe('Artwork rendering', () => {
    it('shows album art image when URL is present', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Currently Playing Song');

      const img = screen.getByAltText('Currently Playing Song') as HTMLImageElement;
      expect(img.src).toContain('example.com/art.jpg');
    });

    it('shows placeholder when no album art', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue({
        ...mockNowPlaying,
        album_art_url: null,
      });
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Currently Playing Song');

      expect(document.querySelector('.now-playing-placeholder')).toBeInTheDocument();
    });
  });
});
