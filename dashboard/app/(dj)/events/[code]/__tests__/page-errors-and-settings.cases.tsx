import { describe, it, expect, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { EventPageTestContext } from './page-test-context';
import type { Event } from '@/lib/api';

export function registerPageErrorsAndSettings(context: EventPageTestContext) {
  const { eventPageTestState, api, ApiError, EventQueuePage, mockEvent, deferred, mockRequest, mockRequestList, mockCollectionSettings, setupDefaultMocks } = context;


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
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([mockRequest()]));
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
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([]));
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
    it('preserves the edited auto-hide value while a save is pending', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();
      const saveRequest = deferred<Awaited<ReturnType<typeof api.setAutoHideMinutes>>>();
      vi.mocked(api.setAutoHideMinutes).mockReturnValue(saveRequest.promise);

      render(<EventQueuePage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      fireEvent.click(screen.getByText('Event Management'));

      const changeAutoHide = eventPageTestState.capturedManageTabProps.onAutoHideInputChange as (value: string) => void;
      const saveAutoHide = eventPageTestState.capturedManageTabProps.onSaveAutoHide as () => Promise<void>;
      act(() => changeAutoHide('20'));

      let savePromise!: Promise<void>;
      await act(async () => {
        savePromise = saveAutoHide();
        await Promise.resolve();
      });
      expect(eventPageTestState.capturedManageTabProps.savingAutoHide).toBe(true);

      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });

      expect(api.getDisplaySettings).toHaveBeenCalledTimes(2);
      expect(eventPageTestState.capturedManageTabProps.autoHideInput).toBe('20');

      await act(async () => {
        saveRequest.resolve({ now_playing_auto_hide_minutes: 20 } as Awaited<
          ReturnType<typeof api.setAutoHideMinutes>
        >);
        await savePromise;
      });
    });

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
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([]));
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

  describe('Pre-event settings loading', () => {
    it('distinguishes an initial settings load from an absent collection', async () => {
      setupDefaultMocks();
      vi.mocked(api.getCollectionSettings).mockImplementation(() => new Promise(() => {}));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByRole('button', { name: /Pre-Event Voting/ }));

      expect(screen.getByRole('status')).toHaveTextContent('Loading pre-event settings');
      expect(screen.queryByTestId('pre-event-tab')).not.toBeInTheDocument();
    });

    it('shows a retry action after the initial settings load fails', async () => {
      setupDefaultMocks();
      vi.mocked(api.getCollectionSettings)
        .mockRejectedValueOnce(new ApiError('Collection settings unavailable', 503))
        .mockResolvedValueOnce(mockCollectionSettings('live'));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByRole('button', { name: /Pre-Event Voting/ }));

      expect(await screen.findByRole('alert')).toHaveTextContent('Collection settings unavailable');
      expect(screen.queryByTestId('pre-event-tab')).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Retry pre-event settings' }));

      expect(await screen.findByTestId('pre-event-tab')).toHaveTextContent('phase:live');
      expect(api.getCollectionSettings).toHaveBeenCalledTimes(2);
    });

    it('keeps the last successful settings visible when refresh fails', async () => {
      setupDefaultMocks();
      vi.mocked(api.getCollectionSettings)
        .mockResolvedValueOnce(mockCollectionSettings('collection'))
        .mockRejectedValueOnce(new ApiError('Refresh failed', 503));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByRole('button', { name: /Pre-Event Voting/ }));
      expect(await screen.findByTestId('pre-event-tab')).toHaveTextContent('phase:collection');

      fireEvent.click(screen.getByRole('button', { name: 'Refresh pre-event settings' }));

      expect(await screen.findByRole('alert')).toHaveTextContent('Refresh failed');
      expect(screen.getByTestId('pre-event-tab')).toHaveTextContent('phase:collection');
      expect(screen.getByRole('button', { name: 'Retry pre-event settings' })).toBeInTheDocument();
    });

    // Regression for baseline 57cfcdc6867f: an old event response could replace current settings.
    it('ignores settings returned for an event code that is no longer active', async () => {
      setupDefaultMocks();
      vi.mocked(api.getEvent).mockImplementation(async (eventCode) => mockEvent({ code: eventCode }) as Event);
      eventPageTestState.mockEventCode = 'OLD';
      let resolveOldSettings!: (settings: ReturnType<typeof mockCollectionSettings>) => void;
      vi.mocked(api.getCollectionSettings).mockImplementation((code) => {
        if (code === 'OLD') {
          return new Promise((resolve) => { resolveOldSettings = resolve; });
        }
        return Promise.resolve(mockCollectionSettings('live'));
      });

      const { rerender } = render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByRole('button', { name: /Pre-Event Voting/ }));
      await waitFor(() => expect(api.getCollectionSettings).toHaveBeenCalledWith('OLD'));

      eventPageTestState.mockEventCode = 'NEW';
      rerender(<EventQueuePage />);
      await waitFor(() => expect(api.getCollectionSettings).toHaveBeenCalledWith('NEW'));
      expect(await screen.findByTestId('pre-event-tab')).toHaveTextContent('phase:live');

      await act(async () => resolveOldSettings(mockCollectionSettings('collection')));

      expect(screen.getByTestId('pre-event-tab')).toHaveTextContent('phase:live');
    });
  });
}
