import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import type { PlaylistInfo } from '@/lib/api/types';
import { useRecommendationPlaylists } from '../useRecommendationPlaylists';

vi.mock('@/lib/api', () => ({
  api: { getEventPlaylists: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const playlist = (id: string): PlaylistInfo => ({
  id,
  name: `Playlist ${id}`,
  num_tracks: 10,
  description: null,
  cover_url: null,
  source: 'tidal',
});

describe('useRecommendationPlaylists', () => {
  beforeEach(() => vi.clearAllMocks());

  it('ignores a late playlist response after the event code changes', async () => {
    let resolveFirst!: (value: { playlists: PlaylistInfo[] }) => void;
    let resolveSecond!: (value: { playlists: PlaylistInfo[] }) => void;
    vi.mocked(api.getEventPlaylists)
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));

    const { result, rerender } = renderHook(
      ({ code }) => useRecommendationPlaylists(code, vi.fn()),
      { initialProps: { code: 'FIRST' } },
    );

    await act(async () => { void result.current.loadPlaylists(); });
    rerender({ code: 'SECOND' });
    await act(async () => { void result.current.loadPlaylists(); });

    await act(async () => resolveFirst({ playlists: [playlist('stale')] }));
    expect(result.current.playlists).toEqual([]);
    expect(result.current.loadingPlaylists).toBe(true);

    await act(async () => resolveSecond({ playlists: [playlist('current')] }));
    expect(result.current.playlists).toEqual([playlist('current')]);
    expect(result.current.playlistsLoaded).toBe(true);
    expect(result.current.loadingPlaylists).toBe(false);
  });

  it('does not report a pending request failure after unmount', async () => {
    let rejectRequest!: (reason: Error) => void;
    vi.mocked(api.getEventPlaylists).mockReturnValue(
      new Promise((_, reject) => { rejectRequest = reject; }),
    );
    const onError = vi.fn();
    const { result, unmount } = renderHook(() => useRecommendationPlaylists('EVENT', onError));

    await act(async () => { void result.current.loadPlaylists(); });
    unmount();
    await act(async () => rejectRequest(new Error('late failure')));

    expect(onError).not.toHaveBeenCalled();
  });
});
