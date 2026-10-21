import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, type SearchResult } from '@/lib/api';
import { useCollectSearch } from '../useCollectSearch';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

const searchResult = (title: string) => ({ title, artist: 'Artist', source: 'spotify' }) as SearchResult;
const searchEvent = { preventDefault: vi.fn() } as unknown as React.FormEvent;

describe('useCollectSearch stale responses', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('does not publish a prior query after a newer query finishes', async () => {
    const oldSearch = deferred<SearchResult[]>();
    const newSearch = deferred<SearchResult[]>();
    const eventSearch = vi.spyOn(api, 'eventSearch')
      .mockReturnValueOnce(oldSearch.promise)
      .mockReturnValueOnce(newSearch.promise);
    const { result } = renderHook(() => useCollectSearch({ code: 'PARTY7' }));
    act(() => {
      result.current.openSearch();
      result.current.setSearchQuery('older query');
    });
    let first!: Promise<void>;
    act(() => { first = result.current.handleSearch(searchEvent); });

    act(() => result.current.setSearchQuery('current query'));
    let second!: Promise<void>;
    act(() => { second = result.current.handleSearch(searchEvent); });
    await act(async () => {
      newSearch.resolve([searchResult('Current result')]);
      await second;
    });
    await act(async () => {
      oldSearch.resolve([searchResult('Stale result')]);
      await first;
    });

    expect(eventSearch).toHaveBeenNthCalledWith(1, 'PARTY7', 'older query');
    expect(eventSearch).toHaveBeenNthCalledWith(2, 'PARTY7', 'current query');
    expect(result.current.searchResults.map((item) => item.title)).toEqual(['Current result']);
    expect(result.current.searching).toBe(false);
  });

  it('does not repopulate results when a search resolves after its modal closes', async () => {
    const pending = deferred<SearchResult[]>();
    vi.spyOn(api, 'eventSearch').mockReturnValue(pending.promise);
    const { result } = renderHook(() => useCollectSearch({ code: 'PARTY7' }));
    act(() => {
      result.current.openSearch();
      result.current.setSearchQuery('song');
    });
    let request!: Promise<void>;
    act(() => { request = result.current.handleSearch(searchEvent); });
    act(() => result.current.closeSearch());
    await act(async () => {
      pending.resolve([searchResult('Late result')]);
      await request;
    });

    expect(result.current.searchOpen).toBe(false);
    expect(result.current.searchResults).toEqual([]);
    expect(result.current.searching).toBe(false);
  });

  it('discards metadata enrichment after the search session closes', async () => {
    const enrichment = deferred<Array<{
      title: string;
      artist: string;
      bpm: number | null;
      key: string | null;
      genre: string | null;
    }>>();
    vi.spyOn(api, 'eventSearch').mockResolvedValue([searchResult('Search result')]);
    vi.spyOn(api, 'enrichPreview').mockReturnValue(enrichment.promise);
    const { result } = renderHook(() => useCollectSearch({ code: 'PARTY7' }));
    act(() => {
      result.current.openSearch();
      result.current.setSearchQuery('song');
    });
    await act(async () => result.current.handleSearch(searchEvent));
    let enrich!: Promise<void>;
    act(() => { enrich = result.current.handleVibesToggle(); });
    expect(result.current.sortByVibes).toBe(true);

    act(() => {
      result.current.closeSearch();
      result.current.openSearch();
    });
    await act(async () => {
      enrichment.resolve([{ title: 'Search result', artist: 'Artist', bpm: 120, key: '8A', genre: 'house' }]);
      await enrich;
    });

    expect(result.current.enrichedResults).toEqual([]);
    expect(result.current.sortByVibes).toBe(false);
    expect(result.current.enriching).toBe(false);
  });

  it.each([403, 404, 410, 422, 429, 503])(
    'does not fall back to DJ search for event-search status %i',
    async (status) => {
      const eventSearch = vi.spyOn(api, 'eventSearch')
        .mockRejectedValue(new ApiError('private server detail', status));
      const globalSearch = vi.spyOn(api, 'search');
      const { result } = renderHook(() => useCollectSearch({ code: 'PARTY7' }));
      act(() => {
        result.current.openSearch();
        result.current.setSearchQuery('song');
      });

      await act(async () => result.current.handleSearch(searchEvent));

      expect(eventSearch).toHaveBeenCalledOnce();
      expect(globalSearch).not.toHaveBeenCalled();
      expect(result.current.searchError).toBe('Song search is unavailable. Please try again.');
      expect(result.current.searchResults).toEqual([]);
    },
  );

  it('does not fall back to DJ search after a transport error, and clears the safe error on retry', async () => {
    const eventSearch = vi.spyOn(api, 'eventSearch')
      .mockRejectedValueOnce(new TypeError('private network detail'))
      .mockResolvedValueOnce([searchResult('Recovered result')]);
    const globalSearch = vi.spyOn(api, 'search');
    const { result } = renderHook(() => useCollectSearch({ code: 'PARTY7' }));
    act(() => {
      result.current.openSearch();
      result.current.setSearchQuery('song');
    });

    await act(async () => result.current.handleSearch(searchEvent));
    expect(result.current.searchError).toBe('Song search is unavailable. Please try again.');
    expect(result.current.searchResults).toEqual([]);
    expect(globalSearch).not.toHaveBeenCalled();

    await act(async () => result.current.handleSearch(searchEvent));
    expect(result.current.searchError).toBeNull();
    expect(result.current.searchResults.map((item) => item.title)).toEqual(['Recovered result']);
    expect(eventSearch).toHaveBeenCalledTimes(2);
    expect(globalSearch).not.toHaveBeenCalled();
  });

  it('reports sanitized enrichment failure and allows retry without losing search results', async () => {
    vi.spyOn(api, 'eventSearch').mockResolvedValue([searchResult('Search result')]);
    const enrichPreview = vi.spyOn(api, 'enrichPreview')
      .mockRejectedValueOnce(new Error('private backend URL and response detail'))
      .mockResolvedValueOnce([{ title: 'Search result', artist: 'Artist', bpm: 120, key: '8A', genre: 'House' }]);
    const { result } = renderHook(() => useCollectSearch({ code: 'PARTY7' }));
    act(() => {
      result.current.openSearch();
      result.current.setSearchQuery('song');
    });
    await act(async () => result.current.handleSearch(searchEvent));

    await act(async () => result.current.handleVibesToggle());
    expect(result.current.searchError).toBe('Could not apply vibe metadata. Please try again.');
    expect(result.current.searchError).not.toContain('private backend');
    expect(result.current.sortByVibes).toBe(false);
    expect(result.current.searchResults.map((item) => item.title)).toEqual(['Search result']);
    expect(result.current.enrichedResults).toEqual([]);
    expect(result.current.enriching).toBe(false);

    await act(async () => result.current.handleVibesToggle());
    expect(enrichPreview).toHaveBeenCalledTimes(2);
    expect(result.current.searchError).toBeNull();
    expect(result.current.sortByVibes).toBe(true);
    expect(result.current.enrichedResults[0]).toMatchObject({ title: 'Search result', bpm: 120, key: '8A' });
  });
});
