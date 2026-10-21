import { describe, it, expect, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import type { EventPageTestContext } from './page-test-context';

export function registerProviderAndDisplay(context: EventPageTestContext) {
  const { eventPageTestState, api, ApiError, EventQueuePage, mockEvent, mockRequest, mockRequestList, setupDefaultMocks } = context;


  describe('Display settings via ManageTab', () => {
    it('passes toggle handlers to ManageTab', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      fireEvent.click(screen.getByText('Event Management'));

      expect(typeof eventPageTestState.capturedManageTabProps.onToggleRequests).toBe('function');
      expect(typeof eventPageTestState.capturedManageTabProps.onToggleNowPlaying).toBe('function');
      expect(typeof eventPageTestState.capturedManageTabProps.onToggleDisplayOnly).toBe('function');
      expect(typeof eventPageTestState.capturedManageTabProps.onBannerSelect).toBe('function');
    });

    it('onToggleRequests calls setRequestsOpen', async () => {
      setupDefaultMocks();
      vi.mocked(api.setRequestsOpen).mockResolvedValue(undefined as never);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onToggleRequests = eventPageTestState.capturedManageTabProps.onToggleRequests as () => Promise<void>;
      await act(async () => { await onToggleRequests(); });

      expect(api.setRequestsOpen).toHaveBeenCalledWith('TEST', false);
    });

    it('onToggleNowPlaying calls setNowPlayingVisibility', async () => {
      setupDefaultMocks();
      vi.mocked(api.setNowPlayingVisibility).mockResolvedValue(undefined as never);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onToggleNowPlaying = eventPageTestState.capturedManageTabProps.onToggleNowPlaying as () => Promise<void>;
      await act(async () => { await onToggleNowPlaying(); });

      expect(api.setNowPlayingVisibility).toHaveBeenCalledWith('TEST', true);
    });

    it('onToggleDisplayOnly calls setKioskDisplayOnly', async () => {
      setupDefaultMocks();
      vi.mocked(api.setKioskDisplayOnly).mockResolvedValue(undefined as never);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      fireEvent.click(screen.getByText('Event Management'));

      const onToggleDisplayOnly = eventPageTestState.capturedManageTabProps.onToggleDisplayOnly as () => Promise<void>;
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

      const onConnectTidal = eventPageTestState.capturedManageTabProps.onConnectTidal as () => Promise<void>;
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

      const onConnectTidal = eventPageTestState.capturedManageTabProps.onConnectTidal as () => Promise<void>;
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

      const onConnectTidal = eventPageTestState.capturedManageTabProps.onConnectTidal as () => Promise<void>;
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

      const onConnectBeatport = eventPageTestState.capturedManageTabProps.onConnectBeatport as () => void;
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

      const onConnectBeatport = eventPageTestState.capturedManageTabProps.onConnectBeatport as () => void;
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

      expect(typeof eventPageTestState.capturedManageTabProps.onBannerSelect).toBe('function');
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
      const onBannerSelect = eventPageTestState.capturedManageTabProps.onBannerSelect as (
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

      expect(await screen.findByTestId('now-playing-badge')).toBeInTheDocument();
    });

    it('hides badge when expired', async () => {
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getArchivedEvents).mockResolvedValue([{
        ...mockEvent(), status: 'expired' as const, request_count: 0, archived_at: null,
      }]);
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
      await screen.findByText('Test Event');

      expect(screen.queryByTestId('qr-code')).not.toBeInTheDocument();
    });
  });

  describe('Delete request', () => {
    it('calls deleteRequest via handler', async () => {
      setupDefaultMocks();
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([mockRequest()]));
      vi.mocked(api.deleteRequest).mockResolvedValue(undefined);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onDeleteRequest = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onDeleteRequest as (id: number) => Promise<void>;
      await act(async () => { await onDeleteRequest(1); });

      expect(api.deleteRequest).toHaveBeenCalledWith(1);
    });
  });

  describe('Refresh metadata', () => {
    it('calls refreshRequestMetadata via handler', async () => {
      setupDefaultMocks();
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([mockRequest()]));
      vi.mocked(api.refreshRequestMetadata).mockResolvedValue(
        mockRequest({ genre: 'Electronic', bpm: 128 }),
      );

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onRefreshMetadata = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onRefreshMetadata as (id: number) => Promise<void>;
      await act(async () => { await onRefreshMetadata(1); });

      expect(api.refreshRequestMetadata).toHaveBeenCalledWith(1);
    });
  });

  describe('Reject all', () => {
    it('calls rejectAllRequests via handler', async () => {
      setupDefaultMocks();
      vi.mocked(api.rejectAllRequests).mockResolvedValue({ status: 'ok', count: 0 });
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([]));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onRejectAll = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onRejectAll as () => Promise<void>;
      await act(async () => { await onRejectAll(); });

      expect(api.rejectAllRequests).toHaveBeenCalledWith('TEST');
    });
  });

  describe('Back link', () => {
    it('shows back link to events', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const backLink = screen.getByText(/Back to Dashboard/);
      expect(backLink.closest('a')).toHaveAttribute('href', '/dashboard');
    });
  });
}
