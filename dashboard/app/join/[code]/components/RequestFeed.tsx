'use client';

import { useState } from 'react';
import { PUBLIC_PAGE_MAX, type GuestRequestInfo } from '@/lib/api';
import Sparks from './Sparks';
import TickNumber from './TickNumber';
import { ACCENT, ACCENT2 } from '../join-constants';
import { artGradient } from './JoinVisuals';

type TabView = 'leaderboard' | 'recent' | 'mine';

interface FeedVotingState {
  localVoteDeltas: Record<number, number>;
  maxVotes: number;
  sparkId: number | null;
  votedIds: Set<number>;
  votingId: number | null;
  voteError: string | null;
  clearSpark: () => void;
  handleVote: (requestId: number) => void;
  retryVote: () => void;
}

interface RequestFeedProps {
  guestRequests: GuestRequestInfo[];
  leaderboardSorted: GuestRequestInfo[];
  myRequestIds: Set<number>;
  total: number;
  voting: FeedVotingState;
  onLoadMore: () => void;
  onSelectRequest: (request: GuestRequestInfo) => void;
}

export default function RequestFeed({
  guestRequests,
  leaderboardSorted,
  myRequestIds,
  total,
  voting,
  onLoadMore,
  onSelectRequest,
}: RequestFeedProps) {
  const [activeTab, setActiveTab] = useState<TabView>('leaderboard');
  const surface = 'rgba(255,255,255,0.04)';
  const border = 'rgba(255,255,255,0.08)';
  const subFg = 'rgba(255,255,255,0.5)';
  const subFg2 = 'rgba(255,255,255,0.35)';
  const tabRows =
    activeTab === 'leaderboard'
      ? leaderboardSorted
      : activeTab === 'recent'
        ? guestRequests
        : guestRequests.filter((request) => myRequestIds.has(request.id));

  return (
    <>
      {voting.voteError && (
        <div role="alert" style={{ padding: '8px 16px', color: 'var(--color-danger)', textAlign: 'center' }}>
          {voting.voteError}{' '}
          <button type="button" onClick={voting.retryVote} disabled={voting.votingId !== null}>
            Retry vote
          </button>
        </div>
      )}

      <div className="gst-tabs" style={{ position: 'relative', zIndex: 1 }}>
        {(['leaderboard', 'recent', 'mine'] as TabView[]).map((tab) => (
          <button
            key={tab}
            className={`gst-tab${activeTab === tab ? ' active' : ''}`}
            onClick={() => setActiveTab(tab)}
            style={{
              color: activeTab === tab ? '#06060a' : subFg,
              border: activeTab === tab ? 'none' : `1px solid ${border}`,
            }}
          >
            {tab === 'leaderboard' ? 'LEADERBOARD' : tab === 'recent' ? 'RECENT' : 'MINE'}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, color: subFg, letterSpacing: 1.2 }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: ACCENT, animation: 'gst-live-pulse 1.6s infinite' }} />
          LIVE
        </div>
      </div>

      <div style={{ padding: '0 12px', position: 'relative', zIndex: 1 }}>
        {tabRows.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '2.5rem 0', color: subFg, fontSize: 16.9 }}>
            {activeTab === 'mine' ? 'No requests from you yet.' : 'No requests yet. Be the first!'}
          </div>
        ) : (
          tabRows.map((request, index) => {
            const effectiveVotes = request.vote_count + (voting.localVoteDeltas[request.id] ?? 0);
            const pct = (effectiveVotes / voting.maxVotes) * 100;
            const isTop3 = activeTab === 'leaderboard' && index < 3;
            const rankColors = [ACCENT, '#fff', subFg];
            const isMine = myRequestIds.has(request.id);
            const isVoted = voting.votedIds.has(request.id) || isMine;

            return (
              <div
                key={request.id}
                className="gst-tower-row guest-request-item"
                style={{
                  background: isMine ? `${ACCENT}14` : surface,
                  border: `1px solid ${isMine ? `${ACCENT}50` : border}`,
                }}
                onClick={() => onSelectRequest(request)}
              >
                <div style={{
                  position: 'absolute', top: 0, left: 0, bottom: 0,
                  width: `${pct}%`,
                  background: `linear-gradient(90deg, ${isTop3 ? ACCENT : ACCENT2}1c, transparent 85%)`,
                  pointerEvents: 'none',
                  transition: 'width 360ms cubic-bezier(.2,.8,.2,1)',
                }} />

                {index === 0 && activeTab === 'leaderboard' && (
                  <div style={{
                    position: 'absolute', left: 0, right: 0, top: 0, height: 1,
                    background: `linear-gradient(90deg, transparent, ${ACCENT}, transparent)`,
                  }} />
                )}

                <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 9, width: '100%' }}>
                  {activeTab === 'leaderboard' && (
                    <div style={{
                      width: 32, height: 32, flexShrink: 0, borderRadius: 8, position: 'relative',
                      background: isTop3 ? rankColors[index] : 'transparent',
                      border: isTop3 ? 'none' : `1px solid ${border}`,
                      color: isTop3 ? '#000' : subFg2,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: 'var(--font-mono, monospace)', fontSize: 14, fontWeight: 800,
                      boxShadow: index === 0 ? `0 0 14px ${ACCENT}50` : 'none',
                    }}>
                      {index + 1}
                      <Sparks accent={ACCENT} accent2={ACCENT2} fire={voting.sparkId === request.id} onDone={voting.clearSpark} />
                    </div>
                  )}

                  <div style={{
                    width: 46, height: 46, borderRadius: 8, flexShrink: 0,
                    background: artGradient(request.title + request.artist), overflow: 'hidden',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 12.1, fontWeight: 800, color: '#fff',
                  }}>
                    {request.artwork_url
                      ? <img src={request.artwork_url} alt={request.title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      : `${request.title[0] ?? '?'}${request.artist[0] ?? ''}`.toUpperCase()
                    }
                  </div>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 16.4, fontWeight: 700, letterSpacing: -0.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>
                        {request.title}
                      </span>
                      {isMine && (
                        <span className="gst-tag" style={{ color: ACCENT, background: `${ACCENT}14`, border: `1px solid ${ACCENT}55` }}>YOU</span>
                      )}
                      {request.status === 'accepted' && (
                        <span className="gst-tag" style={{ color: '#a78bfa', background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.3)' }}>
                          Accepted
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 15.2, color: subFg, marginTop: 2, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {request.artist}
                    </div>
                    {request.nickname && (
                      <div style={{ fontSize: 12.1, color: subFg2, marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        Requested by {request.nickname}
                        {request.requester_verified && <span style={{ color: '#22c55e', marginLeft: 4 }}>✓</span>}
                      </div>
                    )}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0, marginLeft: 'auto' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                      <TickNumber
                        value={effectiveVotes}
                        style={{
                          fontFamily: 'var(--font-mono, monospace)', fontSize: 18.2, fontWeight: 800,
                          lineHeight: '1', color: isTop3 ? rankColors[index] : '#fff',
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      />
                      <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 9, color: subFg, letterSpacing: 1, marginTop: 2 }}>
                        VOTES
                      </span>
                    </div>
                    <button
                      onClick={(event) => { event.stopPropagation(); voting.handleVote(request.id); }}
                      disabled={voting.votingId === request.id || isMine}
                      style={{
                        width: 38, height: 38, borderRadius: 8,
                        background: isVoted ? ACCENT : 'transparent',
                        border: `1px solid ${isVoted ? ACCENT : border}`,
                        color: isVoted ? '#000' : '#fff',
                        cursor: isMine ? 'default' : 'pointer',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        transition: 'all 160ms',
                        boxShadow: isVoted ? `0 0 14px ${ACCENT}80` : 'none',
                        opacity: voting.votingId === request.id ? 0.6 : 1,
                      }}
                      title={isMine ? 'This is your request' : undefined}
                    >
                      <svg width="11" height="7" viewBox="0 0 11 7" fill="none" aria-hidden="true">
                        <path d="M1 6L5.5 1L10 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                      <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', opacity: 0 }}>▲</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}

        {activeTab !== 'mine' && guestRequests.length < Math.min(total, PUBLIC_PAGE_MAX) ? (
          <button
            type="button"
            onClick={onLoadMore}
            style={{
              width: '100%', marginTop: 10, padding: '13px 16px', borderRadius: 10,
              background: surface, border: `1px solid ${border}`, color: '#fff',
              fontFamily: 'var(--font-mono, monospace)', fontSize: 11.5, fontWeight: 700,
              letterSpacing: 1.4, cursor: 'pointer',
            }}
          >
            LOAD MORE · {Math.max(Math.min(total, PUBLIC_PAGE_MAX) - guestRequests.length, 0)} MORE
          </button>
        ) : tabRows.length > 0 ? (
          <div style={{ textAlign: 'center', padding: '10px 0 0', fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, color: subFg2, letterSpacing: 1.5 }}>
            ◇ END OF QUEUE ◇
          </div>
        ) : null}
      </div>
    </>
  );
}
