import { describe, it, expect, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import type { EventPageTestContext } from './page-test-context';

export function registerPageActions(context: EventPageTestContext) {
  const { eventPageTestState, mockPush, api, ApiError, EventQueuePage, mockEvent, mockRequest, mockRequestList, setupDefaultMocks } = context;


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
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([mockRequest()]));
      vi.mocked(api.updateRequestStatus).mockRejectedValue(new ApiError('Status error', 400));

      render(<EventQueuePage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Trigger an error via the update handler
      const onUpdateStatus = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onUpdateStatus as (id: number, s: string) => Promise<void>;
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

      expect(typeof (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onUpdateStatus).toBe('function');
    });

    it('calls updateRequestStatus via handler', async () => {
      setupDefaultMocks();
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([mockRequest()]));
      vi.mocked(api.updateRequestStatus).mockResolvedValue(mockRequest({ status: 'accepted' }));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onUpdateStatus = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onUpdateStatus as (id: number, s: string) => Promise<void>;
      await act(async () => { await onUpdateStatus(1, 'accepted'); });

      expect(api.updateRequestStatus).toHaveBeenCalledWith(1, 'accepted');
    });

    it('shows error on status update failure', async () => {
      setupDefaultMocks();
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([mockRequest()]));
      vi.mocked(api.updateRequestStatus).mockRejectedValue(new ApiError('Invalid transition', 400));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onUpdateStatus = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onUpdateStatus as (id: number, s: string) => Promise<void>;
      await act(async () => { await onUpdateStatus(1, 'played'); });

      expect(screen.getByText('Invalid transition')).toBeInTheDocument();
    });
  });

  describe('Accept all requests', () => {
    it('calls acceptAllRequests', async () => {
      setupDefaultMocks();
      vi.mocked(api.acceptAllRequests).mockResolvedValue({ status: 'ok', accepted_count: 1 });
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([mockRequest({ status: 'accepted' })]));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onAcceptAll = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onAcceptAll as () => Promise<void>;
      await act(async () => { await onAcceptAll(); });

      expect(api.acceptAllRequests).toHaveBeenCalledWith('TEST');
    });

    it('shows error on failure', async () => {
      setupDefaultMocks();
      vi.mocked(api.acceptAllRequests).mockRejectedValue(new ApiError('No requests', 400));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      const onAcceptAll = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onAcceptAll as () => Promise<void>;
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
      vi.mocked(api.getRequests).mockResolvedValue(mockRequestList([mockRequest()]));
      vi.mocked(api.exportEventCsv).mockResolvedValue(true);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
      });

      expect(api.exportEventCsv).toHaveBeenCalledWith('TEST');
      expect(screen.getByRole('status')).toHaveTextContent(
        'This CSV contains the first 10,000 requests only.'
      );
    });

    it('shows when play history export is truncated', async () => {
      setupDefaultMocks();
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getArchivedEvents).mockResolvedValue([{
        ...mockEvent(), status: 'expired' as const, request_count: 0, archived_at: null,
      }]);
      vi.mocked(api.exportPlayHistoryCsv).mockResolvedValue(true);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Export Play History' }));
      });

      expect(screen.getByRole('status')).toHaveTextContent(
        'This CSV contains the first 10,000 play history entries only.'
      );
    });

    it('warns when export truncation status cannot be read', async () => {
      setupDefaultMocks();
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getArchivedEvents).mockResolvedValue([{
        ...mockEvent(), status: 'expired' as const, request_count: 0, archived_at: null,
      }]);
      vi.mocked(api.exportEventCsv).mockResolvedValue(null);

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
      });

      expect(screen.getByRole('status')).toHaveTextContent(
        'The download did not include a truncation status. Verify it is complete before relying on it.'
      );
    });

    it('keeps a history warning when a concurrent request export completes without truncation', async () => {
      setupDefaultMocks();
      vi.mocked(api.getEvent).mockRejectedValue(new ApiError('Expired', 410));
      vi.mocked(api.getArchivedEvents).mockResolvedValue([{
        ...mockEvent(), status: 'expired' as const, request_count: 0, archived_at: null,
      }]);

      let resolveRequest!: (truncated: boolean | null) => void;
      let resolveHistory!: (truncated: boolean | null) => void;
      vi.mocked(api.exportEventCsv).mockImplementation(() => new Promise((resolve) => {
        resolveRequest = resolve;
      }));
      vi.mocked(api.exportPlayHistoryCsv).mockImplementation(() => new Promise((resolve) => {
        resolveHistory = resolve;
      }));

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Export Play History' }));
        fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
      });

      await act(async () => {
        resolveHistory(true);
        await Promise.resolve();
      });
      const warning = 'This CSV contains the first 10,000 play history entries only.';
      expect(screen.getByRole('status')).toHaveTextContent(warning);

      await act(async () => {
        resolveRequest(false);
        await Promise.resolve();
      });

      expect(screen.getByRole('status')).toHaveTextContent(warning);
    });
  });
}
