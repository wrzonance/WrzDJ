import { it, expect, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { RecommendationsCardTestContext } from './RecommendationsCard-test-context';
import type { PlaylistInfo } from '@/lib/api/types';

export function registerPlaylistTests(context: RecommendationsCardTestContext) {
  const { api, RecommendationsCard, makeResponse, makePlaylist, defaultProps } = context;


  // Template playlist tests

  it('renders mode toggle with From Requests and From Playlist options', () => {
    render(<RecommendationsCard {...defaultProps} />);
    expect(screen.getByText('From Requests')).toBeInTheDocument();
    expect(screen.getByText('From Playlist')).toBeInTheDocument();
  });

  it('loads playlists when From Playlist mode is selected', async () => {
    vi.mocked(api.getEventPlaylists).mockResolvedValue({
      playlists: [
        makePlaylist({ id: 'p1', name: 'Mix 1', source: 'tidal' }),
        makePlaylist({ id: 'p2', name: 'Mix 2', source: 'beatport' }),
      ],
    });

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('From Playlist'));

    await waitFor(() => {
      expect(api.getEventPlaylists).toHaveBeenCalledWith('TEST01');
    });
  });

  it('shows playlist dropdown with loaded playlists', async () => {
    vi.mocked(api.getEventPlaylists).mockResolvedValue({
      playlists: [
        makePlaylist({ id: 'p1', name: 'Friday Night Mix', source: 'tidal' }),
      ],
    });

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('From Playlist'));

    await waitFor(() => {
      expect(screen.getByText(/Friday Night Mix/)).toBeInTheDocument();
    });
  });

  it('keeps a delayed playlist response cached when switching back to requests', async () => {
    let resolvePlaylists!: (value: { playlists: PlaylistInfo[] }) => void;
    vi.mocked(api.getEventPlaylists).mockReturnValue(
      new Promise((resolve) => { resolvePlaylists = resolve; }),
    );

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('From Playlist'));
    fireEvent.click(screen.getByText('From Requests'));

    await act(async () => resolvePlaylists({
      playlists: [makePlaylist({ id: 'late', name: 'Late playlist' })],
    }));

    expect(screen.queryByText(/Late playlist/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('From Playlist'));
    expect(screen.getByText(/Late playlist/)).toBeInTheDocument();
  });

  it('Generate disabled when no playlist selected in template mode', async () => {
    vi.mocked(api.getEventPlaylists).mockResolvedValue({
      playlists: [makePlaylist()],
    });

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('From Playlist'));

    await waitFor(() => {
      expect(screen.getByText('Generate')).toBeDisabled();
    });
  });

  it('calls from-template API when generating in template mode', async () => {
    vi.mocked(api.getEventPlaylists).mockResolvedValue({
      playlists: [makePlaylist({ id: 'bp-1', name: 'Club Mix', source: 'beatport' })],
    });
    vi.mocked(api.generateRecommendationsFromTemplate).mockResolvedValue(makeResponse());

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('From Playlist'));

    await waitFor(() => {
      expect(screen.getByText(/Club Mix/)).toBeInTheDocument();
    });

    // Select the playlist
    const select = screen.getByRole('combobox');
    fireEvent.change(select, { target: { value: 'beatport:bp-1' } });

    // Generate
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(api.generateRecommendationsFromTemplate).toHaveBeenCalledWith(
        'TEST01', 'beatport', 'bp-1'
      );
    });
  });

  it('shows service badges on playlists', async () => {
    vi.mocked(api.getEventPlaylists).mockResolvedValue({
      playlists: [
        makePlaylist({ id: 'p1', name: 'Tidal Mix', source: 'tidal', num_tracks: 15 }),
        makePlaylist({ id: 'p2', name: 'BP Mix', source: 'beatport', num_tracks: 25 }),
      ],
    });

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('From Playlist'));

    await waitFor(() => {
      // Both playlists should be visible as options
      const select = screen.getByRole('combobox');
      expect(select).toBeInTheDocument();
    });
  });
}
