import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { NowPlayingBadge } from '../NowPlayingBadge';
import type { NowPlayingInfo } from '@/lib/api/types';

const baseNowPlaying: NowPlayingInfo = {
  title: 'Test Song',
  artist: 'Test Artist',
  album: 'Test Album',
  album_art_url: 'https://example.com/art.jpg',
  spotify_uri: null,
  started_at: new Date().toISOString(),
  source: 'stagelinq',
  matched_request_id: null,
  bridge_connected: true,
};

describe('NowPlayingBadge', () => {
  it('renders nothing when nowPlaying is null', () => {
    const { container } = render(<NowPlayingBadge nowPlaying={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders title and artist when nowPlaying is provided', () => {
    render(<NowPlayingBadge nowPlaying={baseNowPlaying} />);
    expect(screen.getByText('Test Song')).toBeDefined();
    expect(screen.getByText('Test Artist')).toBeDefined();
  });

  it('renders album art image when album_art_url is present', () => {
    render(<NowPlayingBadge nowPlaying={baseNowPlaying} />);
    const img = screen.getByAltText('Album art');
    expect(img).toBeDefined();
    expect(img.getAttribute('src')).toBe('https://example.com/art.jpg');
  });

  it('renders placeholder when album_art_url is null', () => {
    const noArt = { ...baseNowPlaying, album_art_url: null };
    render(<NowPlayingBadge nowPlaying={noArt} />);
    expect(screen.queryByAltText('Album art')).toBeNull();
    expect(screen.getByTestId('album-art-placeholder')).toBeDefined();
  });

  it('shows LIVE badge when source is stagelinq', () => {
    render(<NowPlayingBadge nowPlaying={baseNowPlaying} />);
    expect(screen.getByText('LIVE')).toBeDefined();
  });

  it('shows LIVE badge when source is pioneer', () => {
    const pioneer = { ...baseNowPlaying, source: 'pioneer' };
    render(<NowPlayingBadge nowPlaying={pioneer} />);
    expect(screen.getByText('LIVE')).toBeDefined();
  });

  it('does not show LIVE badge when source is request', () => {
    const fromRequest = { ...baseNowPlaying, source: 'request' };
    render(<NowPlayingBadge nowPlaying={fromRequest} />);
    expect(screen.queryByText('LIVE')).toBeNull();
  });

  it('does not show LIVE badge when source is manual', () => {
    const manual = { ...baseNowPlaying, source: 'manual' };
    render(<NowPlayingBadge nowPlaying={manual} />);
    expect(screen.queryByText('LIVE')).toBeNull();
  });

  it('renders spectrum bars', () => {
    render(<NowPlayingBadge nowPlaying={baseNowPlaying} />);
    const bars = screen.getByTestId('spectrum-bars');
    expect(bars).toBeDefined();
    expect(bars.children.length).toBe(5);
  });
});
