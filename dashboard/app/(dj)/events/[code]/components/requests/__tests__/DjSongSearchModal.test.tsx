import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DjSongSearchModal } from '../DjSongSearchModal';
import { api } from '@/lib/api';
import type { SearchResult } from '@/lib/api/types';

vi.mock('@/components/MusicBadges', () => ({
  KeyBadge: () => null,
  BpmBadge: () => null,
  GenreBadge: () => null,
}));
vi.mock('@/components/PreviewPlayer', () => ({ PreviewPlayer: () => null }));

const result: SearchResult = {
  album: 'Album',
  album_art: null,
  artist: 'Artist',
  bpm: 128,
  genre: 'House',
  isrc: 'ISRC123',
  key: '8A',
  popularity: 90,
  preview_url: null,
  source: 'spotify',
  spotify_id: 'track-1',
  title: 'Track One',
  url: 'https://example.test/track-1',
};

describe('DjSongSearchModal', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('does not search an empty query and trims the search sent to the API', async () => {
    const search = vi.spyOn(api, 'eventSearch').mockResolvedValue([result]);
    render(<DjSongSearchModal code="PARTY" onSongAdded={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText('Search for a song or artist...'), {
      target: { value: '  artist title  ' },
    });
    fireEvent.keyDown(screen.getByPlaceholderText('Search for a song or artist...'), { key: 'Enter' });

    expect(await screen.findByText('Track One')).toBeInTheDocument();
    expect(search).toHaveBeenCalledWith('PARTY', 'artist title');
  });

  it('submits selected track metadata, marks it added, and refreshes the queue', async () => {
    vi.spyOn(api, 'eventSearch').mockResolvedValue([result]);
    const submit = vi.spyOn(api, 'submitRequest').mockResolvedValue({ id: 42 } as never);
    const update = vi.spyOn(api, 'updateRequestStatus').mockResolvedValue({ id: 42 } as never);
    const onSongAdded = vi.fn();
    render(<DjSongSearchModal code="PARTY" onSongAdded={onSongAdded} onClose={vi.fn()} />);
    const searchInput = screen.getByPlaceholderText('Search for a song or artist...');
    fireEvent.change(searchInput, { target: { value: '  artist title  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Add' }));

    await waitFor(() => expect(submit).toHaveBeenCalledWith({
      eventCode: 'PARTY',
      artist: 'Artist',
      title: 'Track One',
      sourceUrl: 'https://example.test/track-1',
      rawSearchQuery: '  artist title  ',
      metadata: { source: 'spotify', genre: 'House', bpm: 128, musical_key: '8A', isrc: 'ISRC123' },
    }));
    expect(update).toHaveBeenCalledWith(42, 'accepted');
    expect(onSongAdded).toHaveBeenCalledOnce();
    expect(await screen.findByRole('button', { name: 'Added' })).toBeDisabled();
  });
});
