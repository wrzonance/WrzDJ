import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { JoinPageTestContext } from './page-test-context';

export function registerVoteTests(context: JoinPageTestContext) {
  const { JoinEventPage, mockApi, MockApiError, setupDefaultMocks } = context;


describe('JoinEventPage — vote flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
    mockApi.checkHasRequested.mockResolvedValue({ has_requested: true });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // Regression for baseline 57cfcdc6867f: the tracker is visible in the route and can recover.
  it('shows a failed My Requests load and retries it from the join page', async () => {
    mockApi.getMyRequests
      .mockRejectedValueOnce(new Error('temporary failure'))
      .mockResolvedValueOnce({ requests: [] });

    render(<JoinEventPage />);

    const retry = await screen.findByRole('button', { name: 'Retry loading your requests' });
    expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load your requests");
    fireEvent.click(retry);

    await waitFor(() => expect(mockApi.getMyRequests).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  function controlAnimationFrames() {
    let nextFrameId = 0;
    const pendingFrames = new Map<number, FrameRequestCallback>();
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const frameId = ++nextFrameId;
      pendingFrames.set(frameId, callback);
      return frameId;
    });
    vi.stubGlobal('cancelAnimationFrame', (frameId: number) => {
      pendingFrames.delete(frameId);
    });

    return async () => {
      let flushCount = 0;
      // Applying a rollback can commit a new TickNumber value and enqueue its own frame.
      while (pendingFrames.size > 0 && flushCount < 8) {
        const callbacks = [...pendingFrames.values()];
        pendingFrames.clear();
        const finalFrameTime = performance.now() + 601;
        // Let React commit effects before reading the next pending-frame batch.
        await act(async () => {
          callbacks.forEach((callback) => callback(finalFrameTime));
        });
        flushCount += 1;
      }
      expect(pendingFrames.size).toBe(0);
    };
  }

  it('votes on a request and updates vote count', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 10, title: 'Vote Song', artist: 'Vote Band', status: 'new', vote_count: 2, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    mockApi.publicVoteRequest.mockResolvedValue({ vote_count: 3, has_voted: true, status: 'voted' });

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

  it('toggles a detail-sheet vote off and back on using server counts', async () => {
    const flushAnimationFrames = controlAnimationFrames();
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        {
          id: 13,
          title: 'Detail Track',
          artist: 'Detail Artist',
          status: 'new',
          vote_count: 2,
          artwork_url: null,
          nickname: 'DJ Guest',
          bpm: 128,
          musical_key: '8A',
        },
      ],
      now_playing: null,
    });
    mockApi.publicVoteRequest
      .mockResolvedValueOnce({ vote_count: 3, has_voted: true, status: 'voted' })
      .mockResolvedValueOnce({ vote_count: 3, has_voted: true, status: 'voted' });
    mockApi.publicUnvoteRequest.mockResolvedValue({ vote_count: 2, has_voted: false, status: 'unvoted' });

    render(<JoinEventPage />);
    await waitFor(() => screen.getByText('Detail Track'));
    fireEvent.click(screen.getByText('Detail Track'));

    const detailSheet = screen.getByText('QUEUE · #1').closest('.gst-detail-sheet');
    expect(detailSheet).not.toBeNull();
    expect(within(detailSheet as HTMLElement).getByText('128 BPM')).toBeInTheDocument();
    expect(within(detailSheet as HTMLElement).getByText('8A')).toBeInTheDocument();
    expect(within(detailSheet as HTMLElement).getByText('DJ Guest')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'UPVOTE THIS TRACK' }));

    await waitFor(() => {
      expect(mockApi.publicVoteRequest).toHaveBeenCalledWith(13, expect.any(Function));
      expect(screen.getByRole('button', { name: 'VOTED · TAP TO REMOVE' })).toBeInTheDocument();
    });
    await flushAnimationFrames();
    expect(within(detailSheet as HTMLElement).getByText('3')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'VOTED · TAP TO REMOVE' }));
    await waitFor(() => {
      expect(mockApi.publicUnvoteRequest).toHaveBeenCalledWith(13, expect.any(Function));
      expect(screen.getByRole('button', { name: 'UPVOTE THIS TRACK' })).toBeInTheDocument();
    });
    await flushAnimationFrames();
    expect(within(detailSheet as HTMLElement).getByText('2')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'UPVOTE THIS TRACK' }));
    await waitFor(() => expect(mockApi.publicVoteRequest).toHaveBeenCalledTimes(2));
    await flushAnimationFrames();
    expect(screen.getByRole('button', { name: 'VOTED · TAP TO REMOVE' })).toBeInTheDocument();
    expect(within(detailSheet as HTMLElement).getByText('3')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByText('QUEUE · #1')).not.toBeInTheDocument();
  });

  // Regression for baseline 57cfcdc6867f: failed vote removal must restore the vote and allow retry.
  it('rolls back a failed detail-sheet vote removal and prevents duplicate pending removals', async () => {
    const flushAnimationFrames = controlAnimationFrames();
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 15, title: 'Removable Track', artist: 'Band', status: 'new', vote_count: 2, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    mockApi.publicVoteRequest.mockResolvedValue({ vote_count: 3, has_voted: true, status: 'voted' });
    let rejectUnvote!: (error: Error) => void;
    mockApi.publicUnvoteRequest
      .mockImplementationOnce(() => new Promise((_, reject) => { rejectUnvote = reject; }))
      .mockResolvedValueOnce({ vote_count: 2, has_voted: false, status: 'unvoted' });

    render(<JoinEventPage />);
    await screen.findByText('Removable Track');
    fireEvent.click(screen.getByText('Removable Track'));
    const detailSheet = screen.getByText('QUEUE · #1').closest('.gst-detail-sheet');
    expect(detailSheet).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'UPVOTE THIS TRACK' }));
    await waitFor(() => expect(mockApi.publicVoteRequest).toHaveBeenCalledTimes(1));
    await flushAnimationFrames();

    const removeButton = screen.getByRole('button', { name: 'VOTED · TAP TO REMOVE' });
    fireEvent.click(removeButton);
    await waitFor(() => expect(mockApi.publicUnvoteRequest).toHaveBeenCalledTimes(1));
    expect(removeButton).toBeDisabled();
    fireEvent.click(removeButton);
    expect(mockApi.publicUnvoteRequest).toHaveBeenCalledTimes(1);
    await flushAnimationFrames();
    expect(within(detailSheet as HTMLElement).getByText('2')).toBeInTheDocument();

    await act(async () => rejectUnvote(new MockApiError('Vote removal failed', 503)));
    await flushAnimationFrames();
    expect(within(detailSheet as HTMLElement).getByText('3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'VOTED · TAP TO REMOVE' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'VOTED · TAP TO REMOVE' }));
    await waitFor(() => expect(mockApi.publicUnvoteRequest).toHaveBeenCalledTimes(2));
    await flushAnimationFrames();
    expect(within(detailSheet as HTMLElement).getByText('2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'UPVOTE THIS TRACK' })).toBeInTheDocument();
  });

  it('keeps a guest from voting on or removing a vote from their own request', async () => {
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 16, title: 'My Track', artist: 'Band', status: 'new', vote_count: 2, artwork_url: null, nickname: 'TestUser' },
      ],
      now_playing: null,
    });
    mockApi.getMyRequests.mockResolvedValue({ requests: [{ id: 16 }] });

    render(<JoinEventPage />);
    await screen.findByText('My Track');
    fireEvent.click(screen.getByText('My Track'));

    const ownVoteButton = screen.getByRole('button', { name: 'VOTED · TAP TO REMOVE' });
    expect(ownVoteButton).toBeDisabled();
    fireEvent.click(ownVoteButton);

    expect(mockApi.publicVoteRequest).not.toHaveBeenCalled();
    expect(mockApi.publicUnvoteRequest).not.toHaveBeenCalled();
  });

  // Regression for baseline 57cfcdc6867f: already_voted is a successful API response, not an error.
  it('uses the server success response when the guest already voted', async () => {
    const flushAnimationFrames = controlAnimationFrames();
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 11, title: 'Already Voted', artist: 'Band', status: 'new', vote_count: 1, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    mockApi.publicVoteRequest.mockResolvedValue({
      status: 'already_voted',
      vote_count: 2,
      has_voted: true,
    });

    render(<JoinEventPage />);
    await waitFor(() => screen.getByText('Already Voted'));

    const row = screen.getByText('Already Voted').closest('.guest-request-item');
    expect(row).not.toBeNull();
    const voteButton = within(row as HTMLElement).getByRole('button');
    fireEvent.click(voteButton);

    await waitFor(() => expect(mockApi.publicVoteRequest).toHaveBeenCalledTimes(1));
    await flushAnimationFrames();
    expect(within(row as HTMLElement).getByText('2')).toBeInTheDocument();
    expect(mockApi.publicVoteRequest).toHaveBeenCalledTimes(1);

    fireEvent.click(voteButton);
    expect(mockApi.publicVoteRequest).toHaveBeenCalledTimes(1);
  });

  // Regression for baseline 57cfcdc6867f: an HTTP failure does not prove a vote was recorded.
  it.each([403, 503])('keeps voting retryable after HTTP %i failure', async (status) => {
    const flushAnimationFrames = controlAnimationFrames();
    mockApi.publicVoteRequest.mockReset();
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 14, title: 'Retryable Vote', artist: 'Band', status: 'new', vote_count: 5, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    let rejectVote!: (error: Error) => void;
    mockApi.publicVoteRequest
      .mockImplementationOnce(() => new Promise((_, reject) => { rejectVote = reject; }))
      .mockResolvedValueOnce({ status: 'voted', vote_count: 6, has_voted: true });

    render(<JoinEventPage />);
    await screen.findByText('Retryable Vote');
    const row = screen.getByText('Retryable Vote').closest('.guest-request-item');
    expect(row).not.toBeNull();
    const voteButton = within(row as HTMLElement).getByRole('button');

    fireEvent.click(voteButton);
    await waitFor(() => expect(mockApi.publicVoteRequest).toHaveBeenCalledTimes(1));
    await flushAnimationFrames();
    expect(within(row as HTMLElement).getByText('6')).toBeInTheDocument();
    await act(async () => rejectVote(new MockApiError('Vote failed', status)));

    await flushAnimationFrames();
    expect(within(row as HTMLElement).getByText('5')).toBeInTheDocument();
    fireEvent.click(voteButton);
    await waitFor(() => expect(mockApi.publicVoteRequest).toHaveBeenCalledTimes(2));
    await flushAnimationFrames();
  });

  // Regression for baseline 57cfcdc6867f: failed votes roll back visibly and offer a retry.
  it('shows a retry action after rolling back a failed vote', async () => {
    const flushAnimationFrames = controlAnimationFrames();
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 17, title: 'Retry With Feedback', artist: 'Band', status: 'new', vote_count: 2, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    mockApi.publicVoteRequest
      .mockRejectedValueOnce(new MockApiError('Unavailable', 503))
      .mockResolvedValueOnce({ status: 'voted', vote_count: 3, has_voted: true });

    render(<JoinEventPage />);
    const row = (await screen.findByText('Retry With Feedback')).closest('.guest-request-item');
    expect(row).not.toBeNull();

    fireEvent.click(within(row as HTMLElement).getByRole('button'));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent("Couldn't update your vote"));
    await flushAnimationFrames();
    expect(within(row as HTMLElement).getByText('2')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry vote' }));
    await waitFor(() => expect(mockApi.publicVoteRequest).toHaveBeenCalledTimes(2));
    await flushAnimationFrames();
    expect(within(row as HTMLElement).getByText('3')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('handles rate limited vote gracefully', async () => {
    const flushAnimationFrames = controlAnimationFrames();
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [
        { id: 12, title: 'Rate Limited Song', artist: 'Band', status: 'new', vote_count: 0, artwork_url: null, nickname: null },
      ],
      now_playing: null,
    });
    let rejectVote!: (error: Error) => void;
    const pendingVote = new Promise((_, reject) => {
        rejectVote = reject;
      });
    mockApi.publicVoteRequest.mockReturnValue(pendingVote);

    render(<JoinEventPage />);
    await waitFor(() => screen.getByText('Rate Limited Song'));

    // The vote button shows ▲ symbol with no count (vote_count is 0)
    const voteBtn = screen.getAllByRole('button').find((btn) =>
      btn.closest('.guest-request-item') !== null
    );
    expect(voteBtn).toBeTruthy();
    fireEvent.click(voteBtn!);

    await waitFor(() => expect(mockApi.publicVoteRequest).toHaveBeenCalledTimes(1));

    const requestRow = screen.getByText('Rate Limited Song').closest('.guest-request-item');
    expect(requestRow).not.toBeNull();
    await flushAnimationFrames();
    expect(within(requestRow as HTMLElement).getAllByText('1')).toHaveLength(2);

    await act(async () => {
      rejectVote(new MockApiError('Rate limit', 429));
      await expect(pendingVote).rejects.toMatchObject({ status: 429 });
    });

    await flushAnimationFrames();
    expect(within(requestRow as HTMLElement).getByText('0')).toBeInTheDocument();
    expect(within(requestRow as HTMLElement).getByRole('button')).not.toBeDisabled();
  });
});
}
