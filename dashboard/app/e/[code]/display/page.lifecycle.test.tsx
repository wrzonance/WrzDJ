import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { getMockEventStream, localStorageMock, mockKioskDisplay, mockPush, setMockDisplayCode, setupDefaultMocks } from './pageTestSupport';
import KioskDisplayPage from './page';
import { ApiError, api } from '@/lib/api';

const mockEventStream = getMockEventStream();
describe('KioskDisplayPage', () => {


  describe('Transient error resilience', () => {
    it('ignores an older 404 after a newer SSE refresh succeeds and keeps polling', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      let rejectInitial!: (error: Error) => void;
      vi.mocked(api.getKioskDisplay)
        .mockImplementationOnce(() => new Promise((_, reject) => { rejectInitial = reject; }))
        .mockResolvedValue(mockKioskDisplay);

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(1);

      await act(async () => {
        mockEventStream.handlers?.onRequestsBulkUpdate?.({ action: 'accepted', count: 1 });
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(2);
      expect(screen.getByText('Test Event')).toBeInTheDocument();

      // Regression for baseline 57cfcdc6867f: stale terminal errors could overwrite newer display data.
      await act(async () => rejectInitial(new ApiError('Old event request', 404)));

      expect(screen.getByText('Test Event')).toBeInTheDocument();
      expect(screen.queryByText('Event Not Found')).not.toBeInTheDocument();
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(3);
    });

    it('invalidates old event requests when the route code changes', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      setMockDisplayCode('OLD');
      let rejectOld!: (error: Error) => void;
      vi.mocked(api.getKioskDisplay)
        .mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }))
        .mockResolvedValue(mockKioskDisplay);

      const { rerender } = render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(1);

      setMockDisplayCode('NEW');
      rerender(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(2);
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(screen.getByText('Test Event')).toBeInTheDocument();

      // Regression for baseline 57cfcdc6867f: a prior route's 404 must not poison the new code.
      await act(async () => rejectOld(new ApiError('Old event expired', 404)));

      expect(screen.getByText('Test Event')).toBeInTheDocument();
      expect(screen.queryByText('Event Not Found')).not.toBeInTheDocument();
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(3);
    });

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

  describe('10s polling loop (SSE handles real-time)', () => {
    it('calls loadDisplay on mount', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(api.getKioskDisplay).toHaveBeenCalledTimes(1);
    });

    it('refreshes display immediately after an SSE update', async () => {
      setupDefaultMocks();
      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');
      expect(api.getKioskDisplay).toHaveBeenCalledTimes(1);

      // Regression for baseline 57cfcdc6867f: SSE handlers were wired but never
      // exercised at the display boundary.
      await act(async () => {
        mockEventStream.handlers?.onRequestsBulkUpdate?.({ action: 'accepted', count: 1 });
        await Promise.resolve();
      });

      expect(api.getKioskDisplay).toHaveBeenCalledTimes(2);
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

    it('redirects to /kiosk-pair when assignment returns unassigned (event deleted)', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      localStorageMock.setItem('kiosk_session_token', 'test-session-token');
      localStorageMock.setItem('kiosk_pair_code', 'ABC123');
      vi.mocked(api.getKioskAssignment).mockResolvedValue({
        status: 'unassigned',
        event_code: null,
        event_join_code: null,
        event_name: null,
      });

      render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
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

    it('clears the session-check interval on unmount', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      localStorageMock.setItem('kiosk_session_token', 'test-session-token');
      vi.mocked(api.getKioskAssignment).mockResolvedValue({
        status: 'active',
        event_code: 'TEST123',
        event_join_code: 'JOIN78',
        event_name: 'Test Event',
      });

      const { unmount } = render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(api.getKioskAssignment).toHaveBeenCalledTimes(1);

      unmount();
      await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });

      expect(api.getKioskAssignment).toHaveBeenCalledTimes(1);
    });
  });
});
