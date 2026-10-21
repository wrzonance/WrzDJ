import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api, ApiError, type CollectEventPreview, type CollectLeaderboardResponse, type CollectMyPicksResponse } from '../../../lib/api';

const POLL_MS = 5000;

interface UseCollectPollingOptions {
  code: string;
  tab: 'trending' | 'all';
  displayLimit: number;
  gateComplete: boolean;
  emailVerified: boolean;
  humanState: string;
  reverify: () => Promise<unknown>;
}

export function useCollectPolling({
  code,
  tab,
  displayLimit,
  gateComplete,
  emailVerified,
  humanState,
  reverify,
}: UseCollectPollingOptions) {
  const router = useRouter();
  const [event, setEvent] = useState<CollectEventPreview | null>(null);
  const [leaderboard, setLeaderboard] = useState<CollectLeaderboardResponse | null>(null);
  const [myPicks, setMyPicks] = useState<CollectMyPicksResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!gateComplete || !code) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let pollInFlight = false;
    let refreshRequested = false;
    let stopPolling = false;

    const tick = async () => {
      if (cancelled || stopPolling) return;
      if (pollInFlight) {
        refreshRequested = true;
        return;
      }
      pollInFlight = true;
      try {
        const ev = await api.getCollectEvent(code);
        if (cancelled) return;
        setError(null);
        setEvent(ev);
        if (ev.phase === 'live' || ev.phase === 'closed') {
          if (humanState === 'verified') {
            try {
              const { join_code } = await api.getLiveJoinCode(code);
              if (cancelled) return;
              sessionStorage.setItem(`wrzdj_live_splash_${code}`, '1');
              router.replace(`/join/${join_code}`);
              stopPolling = true;
              return;
            } catch (err) {
              if (err instanceof ApiError && err.status === 403) {
                reverify().catch(() => {});
              }
            }
          }
        } else if (ev.phase === 'collection') {
          const lb = await api.getCollectLeaderboard(code, tab, { limit: displayLimit });
          if (!cancelled) setLeaderboard(lb);
          if (emailVerified) {
            const picks = await api.getCollectMyPicks(code);
            if (!cancelled) setMyPicks(picks);
          }
        }
      } catch (cause) {
        if (!cancelled) {
          setError(
            cause instanceof Error && cause.message.trim()
              ? cause.message
              : 'Unable to load event data. Please try again.',
          );
        }
      } finally {
        pollInFlight = false;
        if (!cancelled && !stopPolling && refreshRequested) {
          refreshRequested = false;
          void tick();
        } else if (!cancelled && !stopPolling && document.visibilityState === 'visible') {
          timer = setTimeout(() => {
            timer = null;
            void tick();
          }, POLL_MS);
        }
      }
    };

    tick();
    const onVisibility = () => {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      if (document.visibilityState === 'visible' && !cancelled) void tick();
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [code, tab, displayLimit, gateComplete, emailVerified, humanState, router, reverify]);

  return { event, leaderboard, myPicks, error, setLeaderboard };
}
