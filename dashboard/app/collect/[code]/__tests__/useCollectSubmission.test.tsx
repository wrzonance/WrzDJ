import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, type SearchResult } from '@/lib/api';
import { useCollectSubmission } from '../useCollectSubmission';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

const song = {
  title: 'Test song',
  artist: 'Test artist',
  source: 'spotify',
  url: 'https://open.spotify.com/track/123',
  album_art: 'https://example.test/art.jpg',
  isrc: 'USABC1234567',
} as SearchResult;

const profile = {
  email_verified: false,
  nickname: 'Guest DJ',
  submission_count: 1,
  submission_cap: 15,
};
const leaderboard = { requests: [], total: 0 };

function createOptions() {
  return {
    code: 'PARTY7',
    nickname: 'Guest DJ',
    tab: 'trending' as const,
    displayLimit: 10,
    setProfile: vi.fn(),
    setLeaderboard: vi.fn(),
    reverify: vi.fn().mockResolvedValue(undefined),
    onSuccess: vi.fn(),
  };
}

describe('useCollectSubmission', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('submits a song, refreshes profile and leaderboard, then closes search', async () => {
    const pending = deferred<{ id: number; is_duplicate: boolean }>();
    const submit = vi.spyOn(api, 'submitCollectRequest').mockReturnValue(pending.promise);
    const getProfile = vi.spyOn(api, 'getCollectProfile').mockResolvedValue(profile);
    const getLeaderboard = vi.spyOn(api, 'getCollectLeaderboard').mockResolvedValue(leaderboard);
    const options = createOptions();
    const { result } = renderHook(() => useCollectSubmission(options));
    let submission!: Promise<void>;

    act(() => { submission = result.current.handleSelectSong(song); });

    expect(result.current.submitting).toBe(true);
    expect(submit).toHaveBeenCalledWith('PARTY7', {
      song_title: 'Test song',
      artist: 'Test artist',
      source: 'spotify',
      source_url: 'https://open.spotify.com/track/123',
      artwork_url: 'https://example.test/art.jpg',
      nickname: 'Guest DJ',
      isrc: 'USABC1234567',
    }, options.reverify);

    await act(async () => {
      pending.resolve({ id: 42, is_duplicate: false });
      await submission;
    });

    expect(getProfile).toHaveBeenCalledWith('PARTY7');
    expect(getLeaderboard).toHaveBeenCalledWith('PARTY7', 'trending', { limit: 10 });
    expect(options.setProfile).toHaveBeenCalledWith({ submission_count: 1, submission_cap: 15 });
    expect(options.setLeaderboard).toHaveBeenCalledWith(leaderboard);
    expect(options.onSuccess).toHaveBeenCalledOnce();
    expect(result.current.submitting).toBe(false);
    expect(result.current.submitError).toBeNull();
  });

  it('keeps duplicate submissions open and reports the existing confirmation', async () => {
    vi.spyOn(api, 'submitCollectRequest').mockResolvedValue({ id: 42, is_duplicate: true });
    vi.spyOn(api, 'getCollectProfile').mockResolvedValue(profile);
    vi.spyOn(api, 'getCollectLeaderboard').mockResolvedValue(leaderboard);
    const options = createOptions();
    const { result } = renderHook(() => useCollectSubmission(options));

    await act(async () => result.current.handleSelectSong(song));

    expect(options.setProfile).toHaveBeenCalled();
    expect(options.setLeaderboard).toHaveBeenCalled();
    expect(options.onSuccess).not.toHaveBeenCalled();
    expect(result.current.submitError).toBe('Great minds think alike! Your vote has been added.');
    expect(result.current.submitting).toBe(false);
  });

  it.each([
    [429, 'Picks limit reached'],
    [409, 'You already picked this one!'],
  ])('maps submission HTTP %s to its existing user message', async (status, message) => {
    vi.spyOn(api, 'submitCollectRequest').mockRejectedValue(new ApiError('rejected', status));
    const getProfile = vi.spyOn(api, 'getCollectProfile');
    const getLeaderboard = vi.spyOn(api, 'getCollectLeaderboard');
    const options = createOptions();
    const { result } = renderHook(() => useCollectSubmission(options));

    await act(async () => result.current.handleSelectSong(song));

    expect(result.current.submitError).toBe(message);
    expect(result.current.submitting).toBe(false);
    expect(getProfile).not.toHaveBeenCalled();
    expect(getLeaderboard).not.toHaveBeenCalled();
    expect(options.onSuccess).not.toHaveBeenCalled();
  });

  it('reports generic submission failures without refreshing or closing', async () => {
    vi.spyOn(api, 'submitCollectRequest').mockRejectedValue(new Error('offline'));
    const options = createOptions();
    const { result } = renderHook(() => useCollectSubmission(options));

    await act(async () => result.current.handleSelectSong(song));

    expect(result.current.submitError).toBe('Failed to submit. Please try again.');
    expect(result.current.submitting).toBe(false);
    expect(options.onSuccess).not.toHaveBeenCalled();
  });

  it.each(['profile', 'leaderboard'] as const)(
    'keeps the modal open and reports a %s refresh failure after submit', async (failedRead) => {
      vi.spyOn(api, 'submitCollectRequest').mockResolvedValue({ id: 42, is_duplicate: false });
      vi.spyOn(api, 'getCollectProfile').mockImplementation(() => (
        failedRead === 'profile' ? Promise.reject(new Error('profile unavailable')) : Promise.resolve(profile)
      ));
      vi.spyOn(api, 'getCollectLeaderboard').mockImplementation(() => (
        failedRead === 'leaderboard'
          ? Promise.reject(new Error('leaderboard unavailable'))
          : Promise.resolve(leaderboard)
      ));
      const options = createOptions();
      const { result } = renderHook(() => useCollectSubmission(options));

      await act(async () => result.current.handleSelectSong(song));

      expect(result.current.submitError).toBe('Failed to submit. Please try again.');
      expect(result.current.submitting).toBe(false);
      expect(options.onSuccess).not.toHaveBeenCalled();
    },
  );

  it('ignores a completed submission callback after its search session resets', async () => {
    const pending = deferred<{ id: number; is_duplicate: boolean }>();
    vi.spyOn(api, 'submitCollectRequest').mockReturnValue(pending.promise);
    vi.spyOn(api, 'getCollectProfile').mockResolvedValue(profile);
    vi.spyOn(api, 'getCollectLeaderboard').mockResolvedValue(leaderboard);
    const options = createOptions();
    const { result } = renderHook(() => useCollectSubmission(options));
    let submission!: Promise<void>;

    act(() => { submission = result.current.handleSelectSong(song); });
    act(() => result.current.resetSubmissionSession());

    await act(async () => {
      pending.resolve({ id: 42, is_duplicate: false });
      await submission;
    });

    expect(options.onSuccess).not.toHaveBeenCalled();
    expect(result.current.submitting).toBe(false);
    expect(result.current.submitError).toBeNull();
  });

  it('does not refresh or notify after unmount while submission is pending', async () => {
    const pending = deferred<{ id: number; is_duplicate: boolean }>();
    vi.spyOn(api, 'submitCollectRequest').mockReturnValue(pending.promise);
    const getProfile = vi.spyOn(api, 'getCollectProfile').mockResolvedValue(profile);
    const getLeaderboard = vi.spyOn(api, 'getCollectLeaderboard').mockResolvedValue(leaderboard);
    const options = createOptions();
    const { result, unmount } = renderHook(() => useCollectSubmission(options));
    let submission!: Promise<void>;

    act(() => { submission = result.current.handleSelectSong(song); });
    unmount();

    await act(async () => {
      pending.resolve({ id: 42, is_duplicate: false });
      await submission;
    });

    expect(getProfile).not.toHaveBeenCalled();
    expect(getLeaderboard).not.toHaveBeenCalled();
    expect(options.onSuccess).not.toHaveBeenCalled();
  });
});
