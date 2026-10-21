'use client';

import { useEffect, useState } from 'react';
import type { CollectLeaderboardRow } from '../../../../lib/api';
import { artGradient } from '@/lib/art-gradient';

const ACCENT = '#00f0ff';
const ACCENT2 = '#ff2bd6';

interface Props {
  rows: CollectLeaderboardRow[];
  tab: 'trending' | 'all';
  onTabChange: (tab: 'trending' | 'all') => void;
  onVote: (requestId: number) => Promise<void>;
  votedIds: ReadonlySet<number>;
  onRowClick?: (row: CollectLeaderboardRow) => void;
}

export default function LeaderboardTabs({ rows, tab, onTabChange, onVote, votedIds, onRowClick }: Props) {
  const [optimistic, setOptimistic] = useState<Record<number, number>>({});
  const [justVoted, setJustVoted] = useState<ReadonlySet<number>>(new Set());

  useEffect(() => {
    setOptimistic((prev) => {
      const next: Record<number, number> = {};
      for (const [id, guess] of Object.entries(prev)) {
        const numericId = Number(id);
        if (!votedIds.has(numericId)) next[numericId] = guess;
      }
      return next;
    });
  }, [rows, votedIds]);

  const hasVoted = (id: number) => votedIds.has(id) || justVoted.has(id);

  const handleVote = async (id: number, currentVotes: number) => {
    if (hasVoted(id)) return;
    setOptimistic((o) => ({ ...o, [id]: currentVotes + 1 }));
    setJustVoted((prev) => { const n = new Set(prev); n.add(id); return n; });
    try {
      await onVote(id);
    } catch {
      setOptimistic((o) => { const n = { ...o }; delete n[id]; return n; });
      setJustVoted((prev) => { const n = new Set(prev); n.delete(id); return n; });
    }
  };

  const border = 'rgba(255,255,255,0.08)';
  const surface = 'rgba(255,255,255,0.04)';
  const subFg = 'rgba(255,255,255,0.5)';
  const subFg2 = 'rgba(255,255,255,0.35)';

  const maxVotes = Math.max(...rows.map(r => optimistic[r.id] ?? r.vote_count), 1);

  return (
    <div>
      {/* Tab strip */}
      <div style={{ display: 'flex', gap: 5, alignItems: 'center', marginBottom: 12 }}>
        {(['trending', 'all'] as const).map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={tab === t}
            onClick={() => onTabChange(t)}
            style={{
              padding: '6px 12px', borderRadius: 99, cursor: 'pointer',
              fontFamily: 'var(--font-mono, monospace)', fontSize: 11.6, fontWeight: 700, letterSpacing: 1.2,
              background: tab === t ? '#fff' : 'transparent',
              color: tab === t ? '#06060a' : subFg,
              border: tab === t ? 'none' : `1px solid ${border}`,
              transition: 'background 150ms, color 150ms',
            }}
          >
            {t === 'trending' ? 'TRENDING' : 'ALL'}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, color: subFg, letterSpacing: 1.2 }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: ACCENT, animation: 'gst-live-pulse 1.6s infinite' }} />
          LIVE
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="collect-empty">
          {tab === 'trending'
            ? 'Not enough songs added yet! Once others contribute this list will grow.'
            : 'No songs yet — be the first to add one!'}
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {rows.map((r, i) => {
            const votes = optimistic[r.id] ?? r.vote_count;
            const voted = hasVoted(r.id);
            const pct = (votes / maxVotes) * 100;
            const isTop3 = i < 3;
            const rankColors = [ACCENT, '#fff', subFg];

            return (
              <div
                key={r.id}
                className="gst-collect-row"
                style={{
                  background: surface,
                  border: `1px solid ${border}`,
                  cursor: onRowClick ? 'pointer' : 'default',
                }}
                onClick={() => onRowClick?.(r)}
              >
                {/* Vote bar fill */}
                <div style={{
                  position: 'absolute', top: 0, left: 0, bottom: 0,
                  width: `${pct}%`,
                  background: `linear-gradient(90deg, ${isTop3 ? ACCENT : ACCENT2}1c, transparent 85%)`,
                  pointerEvents: 'none',
                  transition: 'width 360ms cubic-bezier(.2,.8,.2,1)',
                }} />

                {/* #1 top-edge glow */}
                {i === 0 && (
                  <div style={{ position: 'absolute', left: 0, right: 0, top: 0, height: 1, background: `linear-gradient(90deg, transparent, ${ACCENT}, transparent)` }} />
                )}

                <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 9, width: '100%' }}>
                  {/* Rank bubble */}
                  <div style={{
                    width: 30, height: 30, flexShrink: 0, borderRadius: 7,
                    background: isTop3 ? rankColors[i] : 'transparent',
                    border: isTop3 ? 'none' : `1px solid ${border}`,
                    color: isTop3 ? '#000' : subFg2,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontFamily: 'var(--font-mono, monospace)', fontSize: 13.3, fontWeight: 800,
                    boxShadow: i === 0 ? `0 0 12px ${ACCENT}50` : 'none',
                  }}>
                    {i + 1}
                  </div>

                  {/* Artwork */}
                  <div style={{
                    width: 46, height: 46, borderRadius: 8, flexShrink: 0, overflow: 'hidden',
                    background: artGradient(r.title + r.artist),
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 12.1, fontWeight: 800, color: '#fff',
                  }}>
                    {r.artwork_url
                      ? <img src={r.artwork_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      : `${r.title[0] ?? '?'}${r.artist[0] ?? ''}`.toUpperCase()
                    }
                  </div>

                  {/* Info */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="collect-row-title">{r.title}</div>
                    <div className="collect-row-artist">{r.artist}</div>
                    {r.nickname && (
                      <div className="collect-row-nickname">
                        <em className="nickname-icon">@</em>{r.nickname}
                        {r.requester_verified && <span style={{ color: '#22c55e', marginLeft: 4, fontStyle: 'normal' }}>✓</span>}
                      </div>
                    )}
                  </div>

                  {/* Vote count + button */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0, marginLeft: 'auto' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                      <span style={{
                        fontFamily: 'var(--font-mono, monospace)', fontSize: 18.2, fontWeight: 800,
                        lineHeight: '1', color: isTop3 ? rankColors[i] : '#fff',
                        fontVariantNumeric: 'tabular-nums',
                      }}>
                        {votes}
                      </span>
                      <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 8.5, color: subFg2, letterSpacing: 1, marginTop: 2 }}>
                        VOTES
                      </span>
                    </div>
                    <button
                      type="button"
                      aria-label={voted ? 'upvoted' : 'upvote'}
                      aria-pressed={voted}
                      className={`gst-collect-vote-btn${voted ? ' voted' : ''}`}
                      disabled={voted}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleVote(r.id, r.vote_count);
                      }}
                    >
                      <svg width="11" height="7" viewBox="0 0 11 7" fill="none">
                        <path d="M1 6L5.5 1L10 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
