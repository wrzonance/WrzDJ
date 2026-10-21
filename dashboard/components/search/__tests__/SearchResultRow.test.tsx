import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { SearchResult } from '@/lib/api';
import SearchResultRow from '../SearchResultRow';

const result: SearchResult = {
  title: 'Midnight City',
  artist: 'M83',
  popularity: 73,
  source: 'spotify',
  url: null,
  album_art: null,
  album: null,
  spotify_id: 'track-1',
  genre: null,
  bpm: 120,
  key: null,
  isrc: null,
  preview_url: null,
};

const appearance = {
  surface: '#101018',
  border: '#282838',
  secondaryText: '#a0a0b0',
  title: { fontSize: 18, letterSpacing: -0.2 },
  artist: { fontSize: 15 },
  vibe: { fontSize: 10 },
  alignItems: 'stretch' as const,
  artworkFallback: () => 'linear-gradient(135deg, #123, #456)',
};

describe('SearchResultRow', () => {
  it('renders the song identity, fallback artwork, vibe metadata, and caller indicator', () => {
    const onSelect = vi.fn();
    render(
      <SearchResultRow
        result={result}
        appearance={appearance}
        vibe={{ railColor: '#00f0ff', label: 'IN THE POCKET', color: '#00f0ff' }}
        trailing={<span title="Beatport">B</span>}
        onSelect={onSelect}
        testId="song-result"
      />,
    );

    const row = screen.getByTestId('song-result');
    expect(row).toHaveTextContent('Midnight City');
    expect(row).toHaveTextContent('M83');
    expect(row).toHaveTextContent('IN THE POCKET');
    expect(row).toHaveTextContent('B');
    expect(screen.getByText('M83').closest('div')).toHaveStyle({ color: appearance.secondaryText });
    expect(row.querySelector('img')).toBeNull();
    expect(row.querySelector('div[style*="linear-gradient"]')).not.toBeNull();

    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(result);
  });

  it('keeps an in-progress submission from selecting a result', () => {
    const onSelect = vi.fn();
    render(
      <SearchResultRow
        result={result}
        appearance={appearance}
        trailing={<span title="Popularity">73</span>}
        onSelect={onSelect}
        disabled
        className="vbs-scanning"
      />,
    );

    const row = screen.getByRole('button', { name: /Midnight City M83/ });
    expect(row).toBeDisabled();
    expect(row).toHaveClass('vbs-scanning');
    fireEvent.click(row);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('uses album artwork and album text for the image alternative', () => {
    render(
      <SearchResultRow
        result={{ ...result, album_art: 'https://example.test/cover.jpg', album: 'Hurry Up, We’re Dreaming' }}
        appearance={appearance}
        trailing={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole('img', { name: 'Hurry Up, We’re Dreaming' })).toHaveAttribute(
      'src',
      'https://example.test/cover.jpg',
    );
  });
});
