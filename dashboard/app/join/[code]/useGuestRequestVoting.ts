'use client';

import { useCallback, useMemo, useState, type Dispatch, type SetStateAction } from 'react';
import { api, type GuestRequestInfo } from '@/lib/api';

interface UseGuestRequestVotingOptions {
  guestRequests: GuestRequestInfo[];
  myRequestIds: Set<number>;
  setGuestRequests: Dispatch<SetStateAction<GuestRequestInfo[]>>;
  reverify: () => Promise<void>;
}

export function useGuestRequestVoting({
  guestRequests,
  myRequestIds,
  setGuestRequests,
  reverify,
}: UseGuestRequestVotingOptions) {
  const [localVoteDeltas, setLocalVoteDeltas] = useState<Record<number, number>>({});
  const [votingId, setVotingId] = useState<number | null>(null);
  const [votedIds, setVotedIds] = useState<Set<number>>(new Set());
  const [sparkId, setSparkId] = useState<number | null>(null);
  const [voteError, setVoteError] = useState<string | null>(null);
  const [retryAction, setRetryAction] = useState<{ requestId: number; desiredHasVoted: boolean } | null>(null);

  const leaderboardSorted = useMemo(
    () =>
      [...guestRequests].sort((a, b) => {
        const votesA = a.vote_count + (localVoteDeltas[a.id] ?? 0);
        const votesB = b.vote_count + (localVoteDeltas[b.id] ?? 0);
        return votesB - votesA;
      }),
    [guestRequests, localVoteDeltas],
  );

  const maxVotes = useMemo(
    () =>
      Math.max(
        ...leaderboardSorted.map((request) => request.vote_count + (localVoteDeltas[request.id] ?? 0)),
        1,
      ),
    [leaderboardSorted, localVoteDeltas],
  );

  const changeVote = useCallback(async (requestId: number, desiredHasVoted: boolean) => {
    if (votingId !== null || myRequestIds.has(requestId)) return;

    setVoteError(null);
    setRetryAction(null);
    const delta = desiredHasVoted ? 1 : -1;
    setLocalVoteDeltas((previous) => ({
      ...previous,
      [requestId]: (previous[requestId] ?? 0) + delta,
    }));
    setVotingId(requestId);
    try {
      const result = desiredHasVoted
        ? await api.publicVoteRequest(requestId, reverify)
        : await api.publicUnvoteRequest(requestId, reverify);
      setVotedIds((previous) => {
        const next = new Set(previous);
        if (result.has_voted) next.add(requestId);
        else next.delete(requestId);
        return next;
      });
      setGuestRequests((previous) =>
        previous.map((request) =>
          request.id === requestId ? { ...request, vote_count: result.vote_count } : request,
        ),
      );
      setLocalVoteDeltas((previous) => {
        const next = { ...previous };
        delete next[requestId];
        return next;
      });
    } catch {
      setLocalVoteDeltas((previous) => {
        const next = { ...previous };
        delete next[requestId];
        return next;
      });
      setVoteError("Couldn't update your vote. Please try again.");
      setRetryAction({ requestId, desiredHasVoted });
    } finally {
      setVotingId(null);
    }
  }, [myRequestIds, reverify, setGuestRequests, votingId]);

  const handleVote = useCallback(async (requestId: number) => {
    if (votedIds.has(requestId) || votingId !== null || myRequestIds.has(requestId)) return;

    const rankBefore = leaderboardSorted.findIndex((request) => request.id === requestId);
    const afterDeltas = {
      ...localVoteDeltas,
      [requestId]: (localVoteDeltas[requestId] ?? 0) + 1,
    };
    const sortedAfter = [...guestRequests].sort((a, b) => {
      const votesA = a.vote_count + (afterDeltas[a.id] ?? 0);
      const votesB = b.vote_count + (afterDeltas[b.id] ?? 0);
      return votesB - votesA;
    });
    const rankAfter = sortedAfter.findIndex((request) => request.id === requestId);
    if (rankAfter < 3 && rankBefore >= 3) setSparkId(requestId);

    await changeVote(requestId, true);
  }, [changeVote, guestRequests, leaderboardSorted, localVoteDeltas, myRequestIds, votedIds, votingId]);

  const handleDetailVote = useCallback(async (requestId: number) => {
    if (votingId !== null || myRequestIds.has(requestId)) return;
    if (votedIds.has(requestId)) {
      await changeVote(requestId, false);
    } else {
      await handleVote(requestId);
    }
  }, [changeVote, handleVote, myRequestIds, votedIds, votingId]);

  const clearSpark = useCallback(() => setSparkId(null), []);
  const retryVote = useCallback(() => {
    if (retryAction) void changeVote(retryAction.requestId, retryAction.desiredHasVoted);
  }, [changeVote, retryAction]);

  return {
    clearSpark,
    handleDetailVote,
    handleVote,
    leaderboardSorted,
    localVoteDeltas,
    maxVotes,
    retryVote,
    sparkId,
    votedIds,
    voteError,
    votingId,
  };
}
