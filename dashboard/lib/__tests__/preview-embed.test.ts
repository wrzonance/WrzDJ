import { describe, it, expect } from 'vitest';
import {
  getSpotifyEmbedUrl,
  getTidalEmbedUrl,
  getPreviewSource,
  canEmbed,
  getEmbedUrl,
  type PreviewData,
} from '../preview-embed';

describe('getSpotifyEmbedUrl', () => {
  it('converts a Spotify track URL to embed URL', () => {
    const url = 'https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh';
    expect(getSpotifyEmbedUrl(url)).toBe(
      'https://open.spotify.com/embed/track/4iV5W9uYEdYUVa79Axb7Rh'
    );
  });

  it('converts a Spotify URL with query params', () => {
    const url = 'https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh?si=abc123';
    expect(getSpotifyEmbedUrl(url)).toBe(
      'https://open.spotify.com/embed/track/4iV5W9uYEdYUVa79Axb7Rh'
    );
  });

  it('returns null for non-Spotify URLs', () => {
    expect(getSpotifyEmbedUrl('https://tidal.com/track/12345')).toBeNull();
    expect(getSpotifyEmbedUrl(null)).toBeNull();
  });

  it('returns null for invalid Spotify URLs', () => {
    expect(getSpotifyEmbedUrl('https://open.spotify.com/album/abc')).toBeNull();
    expect(getSpotifyEmbedUrl('https://open.spotify.com/artist/abc')).toBeNull();
  });
});

describe('getTidalEmbedUrl', () => {
  it('converts a Tidal track URL to embed URL', () => {
    const url = 'https://tidal.com/browse/track/12345678';
    expect(getTidalEmbedUrl(url)).toBe(
      'https://embed.tidal.com/tracks/12345678'
    );
  });

  it('handles listen.tidal.com URLs', () => {
    const url = 'https://listen.tidal.com/track/12345678';
    expect(getTidalEmbedUrl(url)).toBe(
      'https://embed.tidal.com/tracks/12345678'
    );
  });

  it('returns null for non-Tidal URLs', () => {
    expect(getTidalEmbedUrl('https://open.spotify.com/track/abc')).toBeNull();
    expect(getTidalEmbedUrl(null)).toBeNull();
  });
});

describe('getPreviewSource', () => {
  it('identifies Spotify source from source field', () => {
    const data: PreviewData = { source: 'spotify', sourceUrl: 'https://open.spotify.com/track/abc' };
    expect(getPreviewSource(data)).toBe('spotify');
  });

  it('identifies Tidal source from source field', () => {
    const data: PreviewData = { source: 'tidal', sourceUrl: 'https://tidal.com/browse/track/123' };
    expect(getPreviewSource(data)).toBe('tidal');
  });

  it('identifies Beatport source from source field', () => {
    const data: PreviewData = { source: 'beatport', sourceUrl: 'https://beatport.com/track/abc/123' };
    expect(getPreviewSource(data)).toBe('beatport');
  });

  it('returns null for unknown sources', () => {
    const data: PreviewData = { source: 'shazam', sourceUrl: null };
    expect(getPreviewSource(data)).toBeNull();
  });
});

describe('canEmbed', () => {
  it('returns true for Spotify tracks', () => {
    expect(canEmbed({ source: 'spotify', sourceUrl: 'https://open.spotify.com/track/abc' })).toBe(true);
  });

  it('returns true for Tidal tracks', () => {
    expect(canEmbed({ source: 'tidal', sourceUrl: 'https://tidal.com/browse/track/123' })).toBe(true);
  });

  it('returns false for Beatport (no embed support)', () => {
    expect(canEmbed({ source: 'beatport', sourceUrl: 'https://beatport.com/track/abc/123' })).toBe(false);
  });

  it('returns false when sourceUrl is null', () => {
    expect(canEmbed({ source: 'spotify', sourceUrl: null })).toBe(false);
  });
});

describe('getEmbedUrl', () => {
  it('returns Spotify embed URL for Spotify source', () => {
    expect(
      getEmbedUrl({ source: 'spotify', sourceUrl: 'https://open.spotify.com/track/abc' })
    ).toBe('https://open.spotify.com/embed/track/abc');
  });

  it('returns Tidal embed URL for Tidal source', () => {
    expect(
      getEmbedUrl({ source: 'tidal', sourceUrl: 'https://tidal.com/browse/track/123' })
    ).toBe('https://embed.tidal.com/tracks/123');
  });

  it('returns null for Beatport source (no embed support)', () => {
    expect(
      getEmbedUrl({ source: 'beatport', sourceUrl: 'https://beatport.com/track/x/1' })
    ).toBeNull();
  });

  it('returns null when sourceUrl is null', () => {
    expect(getEmbedUrl({ source: 'spotify', sourceUrl: null })).toBeNull();
  });

  it('returns null for unknown source', () => {
    expect(
      getEmbedUrl({ source: 'shazam', sourceUrl: 'https://shazam.com/track/123' })
    ).toBeNull();
  });
});

describe('Beatport source detection (host-anchored)', () => {
  it('detects beatport.com and its subdomains by hostname', () => {
    expect(
      getPreviewSource({ sourceUrl: 'https://www.beatport.com/track/strobe/12345', source: 'unknown' })
    ).toBe('beatport');
    expect(
      getPreviewSource({ sourceUrl: 'https://beatport.com/track/strobe/12345', source: 'unknown' })
    ).toBe('beatport');
  });

  it('does not treat a foreign URL that merely mentions beatport.com as Beatport', () => {
    expect(
      getPreviewSource({ sourceUrl: 'https://evil.example/?ref=beatport.com', source: 'unknown' })
    ).toBeNull();
    expect(
      getPreviewSource({ sourceUrl: 'https://beatport.com.evil.example/track/1', source: 'unknown' })
    ).toBeNull();
    expect(getPreviewSource({ sourceUrl: 'not a url beatport.com', source: 'unknown' })).toBeNull();
  });
});

describe('source-field fallback for Beatport', () => {
  it('still honours the source field when the URL is a Beatport host or absent', () => {
    expect(
      getPreviewSource({ source: 'beatport', sourceUrl: 'https://www.beatport.com/track/x/1' })
    ).toBe('beatport');
    expect(getPreviewSource({ source: 'beatport', sourceUrl: null })).toBe('beatport');
  });

  it('refuses to label a foreign URL as Beatport on the strength of the source field', () => {
    expect(getPreviewSource({ source: 'beatport', sourceUrl: 'https://evil.example/' })).toBeNull();
  });
});
