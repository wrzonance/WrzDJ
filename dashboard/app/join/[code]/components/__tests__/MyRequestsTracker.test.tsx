import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, it, expect, vi } from 'vitest';
import MyRequestsTracker from '../MyRequestsTracker';

const { getMyRequests } = vi.hoisted(() => ({ getMyRequests: vi.fn() }));

vi.mock('@/lib/api', () => ({
  api: {
    getMyRequests,
  },
}));

describe('MyRequestsTracker', () => {
  beforeEach(() => {
    getMyRequests.mockReset().mockResolvedValue({
      requests: [{
        id: 1,
        title: 'Test Song',
        artist: 'Test Artist',
        status: 'new',
        artwork_url: null,
        created_at: '2026-05-16T00:00:00Z',
        vote_count: 0,
      }],
    });
  });

  it('art placeholder uses theme-safe background', async () => {
    render(
      <MyRequestsTracker
        eventCode="EVT001"
        refreshKey={0}
        onRequestIdsLoaded={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Test Song')).toBeInTheDocument();
    });

    const placeholder = document.querySelector('div.guest-request-item-art');
    expect(placeholder).not.toBeNull();
    expect(placeholder!).toHaveAttribute('style', expect.stringContaining('var(--card)'));
  });

  it('art placeholder icon uses theme-safe text color', async () => {
    render(
      <MyRequestsTracker
        eventCode="EVT001"
        refreshKey={0}
        onRequestIdsLoaded={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('Test Song')).toBeInTheDocument();
    });

    const placeholder = document.querySelector('div.guest-request-item-art');
    const icon = placeholder!.querySelector('span');
    expect(icon).not.toBeNull();
    expect(icon!).toHaveAttribute('style', expect.stringContaining('var(--text-secondary)'));
  });

  // Regression for baseline 57cfcdc6867f: a failed load must not look like an empty request list.
  it('shows a retry action after a failed load and then renders the loaded request', async () => {
    getMyRequests
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce({ requests: [{
        id: 2,
        title: 'Recovered Song',
        artist: 'Recovered Artist',
        status: 'new',
        artwork_url: null,
        created_at: '2026-05-16T00:00:00Z',
        vote_count: 0,
      }] });

    render(<MyRequestsTracker eventCode="EVT001" refreshKey={0} onRequestIdsLoaded={vi.fn()} />);

    const retry = await screen.findByRole('button', { name: 'Retry loading your requests' });
    expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load your requests");
    fireEvent.click(retry);

    expect(await screen.findByText('Recovered Song')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('treats a successful empty response as empty rather than as a load failure', async () => {
    getMyRequests.mockResolvedValueOnce({ requests: [] });

    render(<MyRequestsTracker eventCode="EVT001" refreshKey={0} onRequestIdsLoaded={vi.fn()} />);

    await waitFor(() => expect(getMyRequests).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry loading your requests' })).not.toBeInTheDocument();
  });
});
