import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { mockKioskDisplay, mockNowPlaying, mockPlayHistory, setupDefaultMocks } from './pageTestSupport';
import KioskDisplayPage from './page';
import { api } from '@/lib/api';

describe('KioskDisplayPage', () => {


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

  describe('Empty states', () => {
    it('shows empty queue message when no accepted requests', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue: [],
        accepted_queue_total: 0,
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

  describe('Accepted-queue pagination (growing window)', () => {
    it('fetches the initial page with limit 100 and offset 0', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);
      await screen.findByText('Test Event');

      expect(api.getKioskDisplay).toHaveBeenCalledWith('TEST123', { limit: 100, offset: 0 });
    });

    it('uses accepted_queue_total for the headline count and a "of" indicator', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue_total: 250, // far more than the 2 loaded items
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await screen.findByText('Test Event');

      // Headline QUEUE stat shows the true total, not the loaded page length
      expect(screen.getByText('250')).toBeInTheDocument();
      // Compact "showing X of Y" indicator (loaded 2 of 250)
      expect(screen.getByText('2 OF 250 TRACKS')).toBeInTheDocument();
    });

    it('shows the plain total when the whole queue is loaded', async () => {
      setupDefaultMocks(); // 2 items, accepted_queue_total: 2

      render(<KioskDisplayPage />);
      await screen.findByText('Test Event');

      expect(screen.getByText('2 TRACKS')).toBeInTheDocument();
    });

    it('grows displayLimit toward PUBLIC_PAGE_MAX when total exceeds the loaded page', async () => {
      vi.useFakeTimers();
      // Every response reports far more accepted requests than the loaded page,
      // so each refresh should bump the requested limit by 100, clamped at 500.
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        accepted_queue_total: 999,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(api.getKioskDisplay).toHaveBeenNthCalledWith(1, 'TEST123', { limit: 100, offset: 0 });

      // Each subsequent poll should request the next 100-larger window.
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenNthCalledWith(2, 'TEST123', { limit: 200, offset: 0 });

      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenNthCalledWith(3, 'TEST123', { limit: 300, offset: 0 });

      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenNthCalledWith(4, 'TEST123', { limit: 400, offset: 0 });

      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenNthCalledWith(5, 'TEST123', { limit: 500, offset: 0 });

      // Clamped at PUBLIC_PAGE_MAX (500) — does not keep growing.
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenNthCalledWith(6, 'TEST123', { limit: 500, offset: 0 });
    });

    it('does not grow the window when the whole queue is already loaded', async () => {
      vi.useFakeTimers();
      setupDefaultMocks(); // total 2, loaded 2

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      // Limit stays at the initial 100 — nothing more to load.
      expect(api.getKioskDisplay).toHaveBeenNthCalledWith(2, 'TEST123', { limit: 100, offset: 0 });
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
});
