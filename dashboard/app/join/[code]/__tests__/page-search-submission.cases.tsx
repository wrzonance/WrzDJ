import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { JoinPageTestContext } from './page-test-context';

export function registerSearchAndSubmission(context: JoinPageTestContext) {
  const { JoinEventPage, mockApi, MockApiError, setupDefaultMocks } = context;


describe('JoinEventPage — search and submission flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  it('shows search form after gate completes', async () => {
    render(<JoinEventPage />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/search for a song/i)).toBeInTheDocument();
    });
  });

  it('shows search results after successful search', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Found Song', artist: 'Found Artist', popularity: 80, source: 'spotify', url: 'spotify://track/1', album_art: null, album: null, spotify_id: '1', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Found' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('Found Song')).toBeInTheDocument();
    });
  });

  it('keeps keyed results in the unknown-key tier when now-playing has no key', async () => {
    // Regression for baseline 57cfcdc6867f: GuestNowPlaying omits musical_key,
    // so key-distance scoring must stay finite instead of making every result "far".
    mockApi.getPublicRequests.mockResolvedValue({
      requests: [],
      now_playing: {
        title: 'Currently Playing',
        artist: 'DJ',
        source: 'spotify',
        album_art_url: null,
      },
    });
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Keyed Candidate', artist: 'Artist', popularity: 80, source: 'spotify', url: null, album_art: null, album: null, spotify_id: 'vibe-1', genre: null, bpm: 120, key: '8A' },
      { title: 'Unknown Key Candidate', artist: 'Artist', popularity: 70, source: 'spotify', url: null, album_art: null, album: null, spotify_id: 'vibe-2', genre: null, bpm: 120, key: null },
    ]);

    render(<JoinEventPage />);
    await waitFor(() => expect(screen.getByText('Currently Playing')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Request a song' }));
    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Candidate' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await screen.findByText('Keyed Candidate');
    fireEvent.click(screen.getByRole('button', { name: /highlight by vibes/i }));

    const keyedResult = screen.getByRole('button', { name: /Keyed Candidate/ });
    expect(within(keyedResult).getByText('BLENDS WELL')).toBeInTheDocument();
    expect(within(keyedResult).queryByText('KEY/TEMPO JUMP')).not.toBeInTheDocument();
  });

  it('shows a retryable error when event search fails without using global search', async () => {
    mockApi.eventSearch.mockRejectedValue(new Error('Not found'));
    mockApi.search.mockResolvedValue([
      { title: 'Generic Song', artist: 'Generic Artist', popularity: 50, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '2', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Generic' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Song search is unavailable. Please try again.',
    );
    expect(mockApi.search).not.toHaveBeenCalled();
    expect(screen.queryByText('Generic Song')).not.toBeInTheDocument();
  });

  it('does not search when query is empty', async () => {
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    expect(mockApi.eventSearch).not.toHaveBeenCalled();
  });

  it('shows confirm request page when song is selected', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Select Me', artist: 'Pick Band', popularity: 70, source: 'spotify', url: null, album_art: null, album: 'My Album', spotify_id: '3', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Select' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => screen.getByText('Select Me'));
    fireEvent.click(screen.getByText('Select Me'));

    await waitFor(() => {
      expect(screen.getByText('Confirm Request')).toBeInTheDocument();
      expect(screen.getByText('Select Me')).toBeInTheDocument();
    });
  });

  it('shows beatport icon for beatport source results', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'BP Track', artist: 'BP Artist', popularity: 90, source: 'beatport', url: 'https://beatport.com/track/1', album_art: null, album: null, spotify_id: null, genre: 'Techno', bpm: 130, key: '4A' },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'BP' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByText('BP Track')).toBeInTheDocument();
      expect(screen.getByTitle('Beatport')).toBeInTheDocument();
    });
  });

  it('shows album art in search result when provided', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Art Song', artist: 'Art Band', popularity: 60, source: 'spotify', url: null, album_art: 'https://example.com/cover.jpg', album: 'Great Album', spotify_id: '4', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Art' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => {
      expect(screen.getByAltText('Great Album')).toBeInTheDocument();
    });
  });

  it('back button from confirm screen goes back to search results', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Back Song', artist: 'Back Band', popularity: 50, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '5', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Back' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Back Song'));
    fireEvent.click(screen.getByText('Back Song'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /back/i }));

    await waitFor(() => {
      expect(screen.getByText('Back Song')).toBeInTheDocument();
    });
  });

  it('submits request and shows success state', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Submit Me', artist: 'Submit Band', popularity: 75, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '6', genre: null, bpm: null, key: null },
    ]);
    mockApi.submitRequest.mockResolvedValue({ id: 100, is_duplicate: false, vote_count: 1 });

    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Submit' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Submit Me'));
    fireEvent.click(screen.getByText('Submit Me'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() => {
      expect(screen.getByText('Request Submitted!')).toBeInTheDocument();
    });
    expect(mockApi.submitRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        eventCode: 'TEST01',
        title: 'Submit Me',
        artist: 'Submit Band',
        rawSearchQuery: 'Submit',
        nickname: 'TestUser',
        metadata: { source: 'spotify' },
      }),
    );
  });

  it('shows "Vote Added!" when submission is a duplicate', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Dupe Song', artist: 'Dupe Band', popularity: 60, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '7', genre: null, bpm: null, key: null },
    ]);
    mockApi.submitRequest.mockResolvedValue({ id: 101, is_duplicate: true, vote_count: 5 });

    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Dupe' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Dupe Song'));
    fireEvent.click(screen.getByText('Dupe Song'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() => {
      expect(screen.getByText('Vote Added!')).toBeInTheDocument();
    });
  });

  it('shows error when submission fails with generic error', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Error Song', artist: 'Error Band', popularity: 55, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '8', genre: null, bpm: null, key: null },
    ]);
    mockApi.submitRequest.mockRejectedValue(new Error('Server fail'));

    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Error' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Error Song'));
    fireEvent.click(screen.getByText('Error Song'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() => {
      expect(screen.getByText('Failed to submit request. Please try again.')).toBeInTheDocument();
    });
  });

  it('closes requests when submission returns 403', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Locked Song', artist: 'Locked Band', popularity: 40, source: 'spotify', url: null, album_art: null, album: null, spotify_id: '9', genre: null, bpm: null, key: null },
    ]);
    mockApi.submitRequest.mockRejectedValue(new MockApiError('Forbidden', 403));

    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Locked' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Locked Song'));
    fireEvent.click(screen.getByText('Locked Song'));

    await waitFor(() => screen.getByText('Confirm Request'));
    fireEvent.click(screen.getByRole('button', { name: /submit request/i }));

    await waitFor(() => {
      // After 403, goes back to search — request closed for this event
      expect(screen.getByText('Requests are closed for this event')).toBeInTheDocument();
    });
  });

  it('shows album art on confirm request screen when present', async () => {
    mockApi.eventSearch.mockResolvedValue([
      { title: 'Art Confirm', artist: 'Art Confirm Band', popularity: 65, source: 'spotify', url: null, album_art: 'https://example.com/art2.jpg', album: 'Art Album', spotify_id: '10', genre: null, bpm: null, key: null },
    ]);
    render(<JoinEventPage />);
    await waitFor(() => screen.getByPlaceholderText(/search for a song/i));

    fireEvent.change(screen.getByPlaceholderText(/search for a song/i), { target: { value: 'Art' } });
    fireEvent.submit(screen.getByRole('button', { name: /search/i }));
    await waitFor(() => screen.getByText('Art Confirm'));
    fireEvent.click(screen.getByText('Art Confirm'));

    await waitFor(() => {
      const img = screen.getByAltText('Art Album');
      expect(img).toHaveAttribute('src', 'https://example.com/art2.jpg');
    });
  });
});
}
