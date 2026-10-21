import { describe, expect, it } from 'vitest';
import { parseSyncResults } from '../event-sync';

describe('parseSyncResults', () => {
  it.each([null, '', '{invalid', 'null', '{}', '"text"', '3'])('returns empty for invalid container %s', (json) => {
    expect(parseSyncResults(json)).toEqual([]);
  });

  it('keeps valid full and sparse server entries while dropping malformed entries', () => {
    const fullEntry = {
      service: 'spotify',
      status: 'added',
      track_id: 'track-1',
      track_title: 'Song',
      track_artist: 'Artist',
      confidence: 0.98,
      url: 'https://open.spotify.com/track/track-1',
      duration_seconds: 210,
      playlist_id: 'playlist-1',
      error: null,
      error_code: null,
      extra: { market: 'US' },
    };
    const sparseTidalEntry = {
      service: 'tidal',
      status: 'not_found',
      track_id: null,
      url: null,
      error: 'Track not found on Tidal',
    };
    const parsed = parseSyncResults(
      JSON.stringify([
        fullEntry,
        sparseTidalEntry,
        null,
        { service: 'spotify' },
        { service: '', status: 'error' },
        { service: 'tidal', status: 'queued' },
        { service: 'tidal', status: ['added'] },
        { service: 'beatport', status: 'error', confidence: 'high' },
        { service: 'beatport', status: 'error', extra: [] },
      ]),
    );

    expect(parsed).toEqual([
      fullEntry,
      {
        service: 'tidal',
        status: 'not_found',
        track_id: null,
        track_title: null,
        track_artist: null,
        confidence: null,
        url: null,
        duration_seconds: null,
        playlist_id: null,
        error: 'Track not found on Tidal',
        error_code: null,
        extra: null,
      },
    ]);
  });
});
