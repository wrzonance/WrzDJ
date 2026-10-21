import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type CollectLeaderboardResponse, type SearchResult } from '../../../lib/api';

interface UseCollectSubmissionOptions {
  code: string;
  nickname: string | null;
  tab: 'trending' | 'all';
  displayLimit: number;
  setProfile: (profile: { submission_count: number; submission_cap: number }) => void;
  setLeaderboard: (leaderboard: CollectLeaderboardResponse) => void;
  reverify: () => Promise<void>;
  onSuccess: () => void;
}

export function useCollectSubmission({
  code,
  nickname,
  tab,
  displayLimit,
  setProfile,
  setLeaderboard,
  reverify,
  onSuccess,
}: UseCollectSubmissionOptions) {
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const sessionRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      sessionRef.current += 1;
    };
  }, []);

  const resetSubmissionSession = () => {
    sessionRef.current += 1;
    setSubmitting(false);
    setSubmitError(null);
  };

  const handleSelectSong = async (song: SearchResult) => {
    const session = sessionRef.current;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await api.submitCollectRequest(code, {
        song_title: song.title,
        artist: song.artist,
        source: song.source as 'spotify' | 'beatport' | 'tidal' | 'manual',
        source_url: song.url ?? undefined,
        artwork_url: song.album_art ?? undefined,
        nickname: nickname ?? undefined,
        isrc: song.isrc ?? undefined,
      }, reverify);

      if (!mountedRef.current) return;
      if (result.is_duplicate && session === sessionRef.current) {
        setSubmitError('Great minds think alike! Your vote has been added.');
      }

      const [profile, leaderboard] = await Promise.all([
        api.getCollectProfile(code),
        api.getCollectLeaderboard(code, tab, { limit: displayLimit }),
      ]);
      if (!mountedRef.current) return;
      setProfile({ submission_count: profile.submission_count, submission_cap: profile.submission_cap });
      setLeaderboard(leaderboard);
      if (!result.is_duplicate && session === sessionRef.current) {
        setSubmitError(null);
        onSuccess();
      }
    } catch (err) {
      if (!mountedRef.current || session !== sessionRef.current) return;
      if (err instanceof ApiError && err.status === 429) {
        setSubmitError('Picks limit reached');
      } else if (err instanceof ApiError && err.status === 409) {
        setSubmitError('You already picked this one!');
      } else {
        setSubmitError('Failed to submit. Please try again.');
      }
    } finally {
      if (mountedRef.current && session === sessionRef.current) setSubmitting(false);
    }
  };

  return { submitting, submitError, resetSubmissionSession, handleSelectSong };
}
