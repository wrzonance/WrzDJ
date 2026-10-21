import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GuestNowPlaying, SearchResult } from '@/lib/api';
import GuestRequestSheet from '../GuestRequestSheet';

vi.mock('@/lib/api', () => ({
  api: {
    eventSearch: vi.fn(),
    search: vi.fn(),
    submitRequest: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

import { api } from '@/lib/api';

const candidates: SearchResult[] = [
  {
    title: 'Keyed Track', artist: 'Artist', popularity: 80, source: 'spotify', url: null,
    album_art: null, album: null, spotify_id: 'keyed', genre: null, bpm: 120, key: '8A',
    isrc: null, preview_url: null,
  },
  {
    title: 'Unknown Key Track', artist: 'Artist', popularity: 70, source: 'spotify', url: null,
    album_art: null, album: null, spotify_id: 'unknown', genre: null, bpm: 120, key: null,
    isrc: null, preview_url: null,
  },
];

const theme = {
  accent: '#5af0a0', accent2: '#46d9ef', surface: '#171a20', border: '#30343d',
  subFg: '#9ba3b2', subFg2: '#6f7784',
};

function renderSheet(nowPlaying: GuestNowPlaying | null) {
  return render(
    <GuestRequestSheet
      code="PARTY7"
      nickname="Guest"
      nowPlaying={nowPlaying}
      setEvent={vi.fn()}
      reverify={vi.fn(async () => {})}
      onClose={vi.fn()}
      onSubmitted={vi.fn()}
      theme={theme}
    />,
  );
}

async function showVibeResults() {
  fireEvent.change(screen.getByPlaceholderText('Search for a song or artist...'), {
    target: { value: 'track' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByRole('button', { name: /Keyed Track/ });
  fireEvent.click(screen.getByRole('button', { name: /HIGHLIGHT BY VIBES/i }));
}

describe('GuestRequestSheet vibe ranking', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.eventSearch).mockResolvedValue(candidates);
  });

  // Regression for baseline 57cfcdc6867f: the public now-playing shape has no key, so scoring stays finite.
  it('applies the neutral unknown-key tier when a playing track has no key metadata', async () => {
    renderSheet({
      title: 'Playing now', artist: 'DJ', source: 'spotify', album_art_url: null,
    });
    await showVibeResults();

    const keyed = screen.getByRole('button', { name: /Keyed Track/ });
    expect(within(keyed).getByText('BLENDS WELL')).toBeInTheDocument();
    expect(within(keyed).queryByText('IN THE POCKET')).not.toBeInTheDocument();
  });

  it('does not add a key-distance penalty when no track is playing', async () => {
    renderSheet(null);
    await showVibeResults();

    const keyed = screen.getByRole('button', { name: /Keyed Track/ });
    const unknownKey = screen.getByRole('button', { name: /Unknown Key Track/ });
    expect(within(keyed).getByText('IN THE POCKET')).toBeInTheDocument();
    expect(within(unknownKey).getByText('BLENDS WELL')).toBeInTheDocument();
  });

  it('does not call DJ-only search after event search fails, and recovers on event-search retry', async () => {
    vi.mocked(api.eventSearch).mockRejectedValueOnce(new Error('event search unavailable'));
    vi.mocked(api.eventSearch).mockResolvedValueOnce(candidates);
    vi.mocked(api.search).mockResolvedValue([]);
    renderSheet(null);
    const input = screen.getByPlaceholderText('Search for a song or artist...');
    const search = screen.getByRole('button', { name: 'Search' });
    fireEvent.change(input, { target: { value: 'track' } });
    fireEvent.click(search);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Song search is unavailable. Please try again.',
    );
    expect(vi.mocked(api.search)).not.toHaveBeenCalled();

    fireEvent.click(search);
    expect(await screen.findByRole('button', { name: /Keyed Track/ })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(vi.mocked(api.eventSearch)).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.search)).not.toHaveBeenCalled();
  });
});
