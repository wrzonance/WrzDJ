import { it, expect, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { RecommendationsCardTestContext } from './RecommendationsCard-test-context';
import type { RecommendationResponse, RecommendedTrack } from '@/lib/api/types';

export function registerLifecycleTests(context: RecommendationsCardTestContext) {
  const { api, RecommendationsCard, makeSuggestion, makeResponse, makePlaylist, defaultProps } = context;


  // Persistence tests

  it('preserves suggestions when switching modes and back', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [
        makeSuggestion({ title: 'Persisted Song', artist: 'DJ Persist' }),
      ],
    }));
    vi.mocked(api.getEventPlaylists).mockResolvedValue({ playlists: [makePlaylist()] });

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText(/DJ Persist/)).toBeInTheDocument();
      expect(screen.getByText('Complete!')).not.toBeDisabled();
    });

    // Switch to From Playlist — suggestions should swap out
    fireEvent.click(screen.getByText('From Playlist'));
    await waitFor(() => expect(screen.getByText(/My Mix/)).toBeInTheDocument());
    expect(screen.queryByText(/DJ Persist/)).not.toBeInTheDocument();

    // Switch back to From Requests — suggestions should be restored
    fireEvent.click(screen.getByText('From Requests'));
    expect(screen.getByText(/DJ Persist/)).toBeInTheDocument();
  });

  // Regression for 57cfcdc: a late result used to overwrite the currently visible mode.
  it('keeps a pending request-mode result out of template mode and restores it to requests', async () => {
    let resolveGeneration!: (response: RecommendationResponse) => void;
    const pendingGeneration = new Promise<RecommendationResponse>((resolve) => {
      resolveGeneration = resolve;
    });
    vi.mocked(api.generateRecommendations).mockReturnValue(pendingGeneration);
    vi.mocked(api.getEventPlaylists).mockResolvedValue({ playlists: [makePlaylist()] });

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => expect(api.generateRecommendations).toHaveBeenCalledWith('TEST01'));

    fireEvent.click(screen.getByText('From Playlist'));
    await waitFor(() => expect(api.getEventPlaylists).toHaveBeenCalledWith('TEST01'));

    await act(async () => {
      resolveGeneration(makeResponse({
        suggestions: [makeSuggestion({ title: 'Request-only song', artist: 'Request result' })],
      }));
    });

    expect(screen.queryByText(/Request result/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('From Requests'));
    expect(screen.getByText(/Request result/)).toBeInTheDocument();
  });

  // Regression for 57cfcdc: late work must remain scoped to the event that started it.
  it('discards a generation result after the event code changes', async () => {
    let resolveGeneration!: (response: RecommendationResponse) => void;
    vi.mocked(api.generateRecommendations).mockReturnValue(
      new Promise((resolve) => { resolveGeneration = resolve; }),
    );

    const { rerender } = render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => expect(api.generateRecommendations).toHaveBeenCalledWith('TEST01'));

    rerender(<RecommendationsCard {...defaultProps} code="TEST02" />);
    await act(async () => resolveGeneration(makeResponse({
      suggestions: [makeSuggestion({ title: 'Old event song', artist: 'Old event artist' })],
    })));

    expect(screen.queryByText(/Old event artist/)).not.toBeInTheDocument();
  });

  // Regression for 57cfcdc: accepting in a cached mode must not mutate another mode's results.
  it('finishes an accepted request-mode track in its cache after switching modes', async () => {
    let resolveAccept!: () => void;
    const pendingAccept = new Promise<void>((resolve) => { resolveAccept = resolve; });
    const sharedTrack = makeSuggestion({ title: 'Same Song', artist: 'Same Artist' });
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [sharedTrack, makeSuggestion({ title: 'Request only', artist: 'Request DJ' })],
    }));
    vi.mocked(api.getEventPlaylists).mockResolvedValue({ playlists: [makePlaylist()] });
    vi.mocked(api.generateRecommendationsFromTemplate).mockResolvedValue(makeResponse({
      suggestions: [sharedTrack, makeSuggestion({ title: 'Template only', artist: 'Template DJ' })],
    }));
    const onAcceptTrack = vi.fn().mockReturnValue(pendingAccept);

    render(<RecommendationsCard {...defaultProps} onAcceptTrack={onAcceptTrack} />);
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => expect(screen.getByText(/Same Artist/)).toBeInTheDocument());
    fireEvent.click(screen.getAllByText('Accept')[0]);
    await waitFor(() => expect(onAcceptTrack).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText('From Playlist'));
    await waitFor(() => expect(screen.getByText(/My Mix/)).toBeInTheDocument());
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'beatport:playlist-1' } });
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => expect(screen.getByText(/Template DJ/)).toBeInTheDocument());

    await act(async () => resolveAccept());
    expect(screen.getByText(/Same Artist/)).toBeInTheDocument();
    expect(screen.getByText(/Template DJ/)).toBeInTheDocument();

    fireEvent.click(screen.getByText('From Requests'));
    expect(screen.queryByText(/Same Artist/)).not.toBeInTheDocument();
    expect(screen.getByText(/Request DJ/)).toBeInTheDocument();
  });

  // Regression for 57cfcdc: an old event's Accept All cannot clear the new event's suggestions.
  it('does not let a pending Accept All clear suggestions for a new event', async () => {
    const acceptResolvers: Array<() => void> = [];
    const onAcceptTrack = vi.fn(() => new Promise<void>((resolve) => acceptResolvers.push(resolve)));
    vi.mocked(api.generateRecommendations)
      .mockResolvedValueOnce(makeResponse({
        suggestions: [
          makeSuggestion({ title: 'Old one', artist: 'Old DJ 1' }),
          makeSuggestion({ title: 'Old two', artist: 'Old DJ 2' }),
        ],
      }))
      .mockResolvedValueOnce(makeResponse({
        suggestions: [makeSuggestion({ title: 'New event song', artist: 'New event DJ' })],
      }));

    const { rerender } = render(
      <RecommendationsCard {...defaultProps} onAcceptTrack={onAcceptTrack} />,
    );
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => expect(screen.getByText('Accept All')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Accept All'));
    await waitFor(() => expect(onAcceptTrack).toHaveBeenCalledTimes(1));

    rerender(
      <RecommendationsCard {...defaultProps} code="TEST02" onAcceptTrack={onAcceptTrack} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Generate|Complete!/ }));
    await waitFor(() => expect(screen.getByText(/New event DJ/)).toBeInTheDocument());

    await act(async () => acceptResolvers[0]());
    await waitFor(() => expect(onAcceptTrack).toHaveBeenCalledTimes(2));
    await act(async () => acceptResolvers[1]());

    expect(screen.getByText(/New event DJ/)).toBeInTheDocument();
  });

  // Regression for 57cfcdc: partial Accept All retries must skip tracks already accepted.
  it('removes each Accept All success immediately and retries only failed tracks', async () => {
    const pending: Array<{ resolve: () => void; reject: (error: Error) => void }> = [];
    const acceptedTracks: RecommendedTrack[] = [];
    const onAcceptTrack = vi.fn((track: RecommendedTrack) => {
      acceptedTracks.push(track);
      return new Promise<void>((resolve, reject) => pending.push({ resolve, reject }));
    });
    const first = makeSuggestion({ title: 'First song', artist: 'First DJ' });
    const second = makeSuggestion({ title: 'Second song', artist: 'Second DJ' });
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [first, second],
    }));

    render(<RecommendationsCard {...defaultProps} onAcceptTrack={onAcceptTrack} />);
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => expect(screen.getByText('Accept All')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Accept All'));
    await waitFor(() => expect(onAcceptTrack).toHaveBeenCalledTimes(1));
    await act(async () => pending[0].resolve());
    await waitFor(() => expect(onAcceptTrack).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/First DJ/)).not.toBeInTheDocument();
    expect(screen.getByText(/Second DJ/)).toBeInTheDocument();

    await act(async () => pending[1].reject(new Error('second track failed')));
    await waitFor(() => expect(screen.getByText(/Failed to accept all tracks/)).toBeInTheDocument());
    fireEvent.click(screen.getByText('Accept All'));
    await waitFor(() => expect(onAcceptTrack).toHaveBeenCalledTimes(3));
    expect(acceptedTracks[2]).toEqual(second);
    await act(async () => pending[2].resolve());

    expect(screen.queryByText(/Second DJ/)).not.toBeInTheDocument();
    expect(acceptedTracks).toEqual([first, second, second]);
  });

  // Regression for 57cfcdc: one pending accept owns the visible busy state until it settles.
  it('serializes individual acceptance and disables competing accept actions', async () => {
    let resolveFirst!: () => void;
    let resolveSecond!: () => void;
    const onAcceptTrack = vi.fn()
      .mockImplementationOnce(() => new Promise<void>((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise<void>((resolve) => { resolveSecond = resolve; }));
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [
        makeSuggestion({ title: 'First song', artist: 'First DJ' }),
        makeSuggestion({ title: 'Second song', artist: 'Second DJ' }),
      ],
    }));

    render(<RecommendationsCard {...defaultProps} onAcceptTrack={onAcceptTrack} />);
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => expect(screen.getByText('Accept All')).toBeInTheDocument());

    fireEvent.click(screen.getAllByText('Accept')[0]);
    await waitFor(() => expect(onAcceptTrack).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Accept')).toBeDisabled();
    expect(screen.getByText('Accept All')).toBeDisabled();
    fireEvent.click(screen.getByText('Accept'));
    expect(onAcceptTrack).toHaveBeenCalledTimes(1);

    await act(async () => resolveFirst());
    await waitFor(() => expect(screen.queryByText(/First DJ/)).not.toBeInTheDocument());
    expect(screen.getByText('Accept')).not.toBeDisabled();
    fireEvent.click(screen.getByText('Accept'));
    await waitFor(() => expect(onAcceptTrack).toHaveBeenCalledTimes(2));
    await act(async () => resolveSecond());
  });

  it('does not start overlapping generation requests', async () => {
    let resolveGeneration!: (response: RecommendationResponse) => void;
    const pendingGeneration = new Promise<RecommendationResponse>((resolve) => {
      resolveGeneration = resolve;
    });
    vi.mocked(api.generateRecommendations).mockReturnValue(pendingGeneration);

    render(<RecommendationsCard {...defaultProps} />);
    act(() => {
      fireEvent.click(screen.getByText('Generate'));
      fireEvent.click(screen.getByText('Generate'));
    });

    expect(api.generateRecommendations).toHaveBeenCalledTimes(1);
    await act(async () => resolveGeneration(makeResponse()));
  });

  it('does not schedule completion work when generation resolves after unmount', async () => {
    vi.useFakeTimers();
    try {
      let resolveGeneration!: (response: RecommendationResponse) => void;
      const pendingGeneration = new Promise<RecommendationResponse>((resolve) => {
        resolveGeneration = resolve;
      });
      vi.mocked(api.generateRecommendations).mockReturnValue(pendingGeneration);

      const { unmount } = render(<RecommendationsCard {...defaultProps} />);
      fireEvent.click(screen.getByText('Generate'));
      unmount();

      await act(async () => resolveGeneration(makeResponse()));
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('Clear removes cached results for current mode', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [makeSuggestion({ title: 'Gone', artist: 'DJ Gone' })],
    }));
    vi.mocked(api.getEventPlaylists).mockResolvedValue({ playlists: [makePlaylist()] });

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText(/DJ Gone/)).toBeInTheDocument();
      expect(screen.getByText('Complete!')).not.toBeDisabled();
    });

    // Clear
    fireEvent.click(screen.getByText('Clear'));
    expect(screen.queryByText(/DJ Gone/)).not.toBeInTheDocument();

    // Switch away and back — should still be cleared
    fireEvent.click(screen.getByText('From Playlist'));
    await waitFor(() => expect(screen.getByText(/My Mix/)).toBeInTheDocument());
    fireEvent.click(screen.getByText('From Requests'));
    expect(screen.queryByText(/DJ Gone/)).not.toBeInTheDocument();
  });
}
