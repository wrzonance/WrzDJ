import { describe, it, expect, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import type { EventPageTestContext } from './page-test-context';

export function registerRequestList(context: EventPageTestContext) {
  const { eventPageTestState, api, EventQueuePage, mockRequest, mockRequestList, setupDefaultMocks } = context;


  describe('Live-display polls use join_code, not collection code', () => {
    it('polls now-playing / bridge-status / history by join_code', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');

      // These three endpoints resolve strictly by join_code (post-#324/#328
      // public-URL contract). This route is keyed on the collection code 'TEST',
      // but the live polls must use the event's join_code 'TSETJO' or the API
      // 404s in a polling loop. Regression for the production console-spam bug.
      expect(api.getNowPlaying).toHaveBeenCalledWith('TSETJO');
      expect(api.getBridgeStatus).toHaveBeenCalledWith('TSETJO');
      expect(api.getPlayHistory).toHaveBeenCalledWith('TSETJO');
      expect(api.getNowPlaying).not.toHaveBeenCalledWith('TEST');
      expect(api.getBridgeStatus).not.toHaveBeenCalledWith('TEST');
      expect(api.getPlayHistory).not.toHaveBeenCalledWith('TEST');

      // DJ-owned endpoints still resolve by the collection code.
      expect(api.getEvent).toHaveBeenCalledWith('TEST');
      expect(api.getRequests).toHaveBeenCalledWith('TEST', expect.anything());
    });
  });

  describe('Client-side status filter + status counts (issue #489)', () => {
    it('computes tab counts from the in-memory set, not server status_counts', async () => {
      setupDefaultMocks();
      // The whole event loads client-side; counts come from the loaded rows'
      // statuses (server `status_counts` is ignored).
      vi.mocked(api.getRequests).mockResolvedValue(
        mockRequestList(
          [
            mockRequest({ id: 1, status: 'new' }),
            mockRequest({ id: 2, status: 'new' }),
            mockRequest({ id: 3, status: 'accepted' }),
          ],
          { status_counts: { all: 999, new: 999, accepted: 999, playing: 9, played: 9, rejected: 9 } },
        ),
      );

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      await waitFor(() =>
        expect(((eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).statusCounts as Record<string, number>).all).toBe(3),
      );

      expect((eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).statusCounts).toEqual({
        all: 3, new: 2, accepted: 1, playing: 0, played: 0, rejected: 0,
      });
    });

    it('changes the filter without a server re-fetch (in-memory)', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      vi.mocked(api.getRequests).mockClear();

      const onFilterChange = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onFilterChange as (f: string) => void;
      await act(async () => { onFilterChange('accepted'); });

      // The filter prop updates, but no new request fetch is triggered.
      expect((eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).filter).toBe('accepted');
      expect(api.getRequests).not.toHaveBeenCalled();
    });
  });

  describe('Client-side sort (issue #489)', () => {
    it('changes a simple sort field without a server re-fetch', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      vi.mocked(api.getRequests).mockClear();

      const onSortFieldChange = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onSortFieldChange as (f: string) => void;
      await act(async () => { onSortFieldChange('upvotes'); });

      // upvotes is a client-sorted field — instant, no network.
      expect((eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).sortField).toBe('upvotes');
      expect(api.getRequests).not.toHaveBeenCalled();
    });

    it('toggles sort direction without a server re-fetch', async () => {
      setupDefaultMocks();

      render(<EventQueuePage />);
      await screen.findByText('Test Event');
      vi.mocked(api.getRequests).mockClear();

      const onSortDirectionToggle = (eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).onSortDirectionToggle as () => void;
      await act(async () => { onSortDirectionToggle(); });

      expect((eventPageTestState.capturedSongTabProps.requestQueue as Record<string, unknown>).sortDirection).toBe('asc');
      expect(api.getRequests).not.toHaveBeenCalled();
    });

    it('does not double-fetch on the initial mount', async () => {
      vi.useFakeTimers();
      setupDefaultMocks();

      render(<EventQueuePage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      // Exactly one initial load from the request hook.
      expect(api.getRequests).toHaveBeenCalledTimes(1);
    });
  });
}
