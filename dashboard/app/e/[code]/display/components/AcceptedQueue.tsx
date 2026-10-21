'use client';

import { useEffect, useRef, useState } from 'react';
import type { KioskDisplay } from '@/lib/api';
import { ACCENT_MAGENTA, withAlpha } from '../displayColors';

const AUTO_SCROLL_INTERVAL = 5000;
const NEW_ITEM_ANIMATION_DURATION = 800;

type AcceptedQueueItem = KioskDisplay['accepted_queue'][number];

interface AcceptedQueueProps {
  items: AcceptedQueueItem[];
  total: number;
  bannerAccent: string;
  displayOnly: boolean;
}

export function AcceptedQueue({ items, total, bannerAccent, displayOnly }: AcceptedQueueProps) {
  const previousIdsRef = useRef<Set<number>>(new Set());
  const queueListRef = useRef<HTMLDivElement>(null);
  const [newItemIds, setNewItemIds] = useState<Set<number>>(new Set());
  const hasMoreThanShown = total > items.length;
  const maxVotes = Math.max(1, ...items.map((item) => item.vote_count));

  useEffect(() => {
    const currentIds = new Set(items.map((item) => item.id));
    const previousIds = previousIdsRef.current;
    const freshIds = new Set([...currentIds].filter((id) => !previousIds.has(id)));

    if (freshIds.size > 0) {
      setNewItemIds(freshIds);
      const timer = setTimeout(() => setNewItemIds(new Set()), NEW_ITEM_ANIMATION_DURATION);
      previousIdsRef.current = currentIds;
      return () => clearTimeout(timer);
    }

    previousIdsRef.current = currentIds;
  }, [items]);

  useEffect(() => {
    if (!displayOnly) return;

    const interval = setInterval(() => {
      const element = queueListRef.current;
      if (!element) return;

      if (element.scrollTop + element.clientHeight >= element.scrollHeight - 10) {
        element.scrollTo({ top: 0, behavior: 'smooth' });
      } else {
        element.scrollBy({ top: 85, behavior: 'smooth' });
      }
    }, AUTO_SCROLL_INTERVAL);

    return () => clearInterval(interval);
  }, [displayOnly]);

  return (
    <div className="kiosk-panel">
      <div className="queue-header">
        <div className="kiosk-panel-label" style={{ color: ACCENT_MAGENTA, marginBottom: 0 }}>
          QUEUE
        </div>
        <div style={{ flex: 1 }} />
        <span className="queue-track-count">
          {hasMoreThanShown ? `${items.length} OF ${total} TRACKS` : `${total} TRACKS`}
        </span>
      </div>
      {items.length > 0 ? (
        <div className="queue-list" ref={queueListRef}>
          {items.map((item, index) => (
            <AcceptedQueueRow
              key={item.id}
              item={item}
              index={index}
              maxVotes={maxVotes}
              bannerAccent={bannerAccent}
              isNew={newItemIds.has(item.id)}
            />
          ))}
        </div>
      ) : (
        <div className="queue-empty">
          <p>No songs in queue yet.</p>
          <p>Be the first to request!</p>
        </div>
      )}
    </div>
  );
}

interface AcceptedQueueRowProps {
  item: AcceptedQueueItem;
  index: number;
  maxVotes: number;
  bannerAccent: string;
  isNew: boolean;
}

function AcceptedQueueRow({ item, index, maxVotes, bannerAccent, isNew }: AcceptedQueueRowProps) {
  const percentage = (item.vote_count / maxVotes) * 100;
  const isTopThree = index < 3;
  const rankColor = index === 0
    ? bannerAccent
    : index === 1
      ? '#fff'
      : index === 2
        ? ACCENT_MAGENTA
        : 'rgba(255,255,255,0.35)';

  return (
    <div
      className={`queue-item${index === 0 ? ' queue-item-top1' : ''}${isNew ? ' queue-item-new' : ''}`}
      style={index === 0 ? {
        background: withAlpha(bannerAccent, 0.12),
        '--banner-accent-50': withAlpha(bannerAccent, 0.5),
        '--banner-accent-30': withAlpha(bannerAccent, 0.3),
        '--banner-accent-20': withAlpha(bannerAccent, 0.2),
      } as React.CSSProperties : undefined}
    >
      <div
        className="queue-item-vote-bar"
        style={{
          width: `${percentage}%`,
          background: `linear-gradient(90deg, ${withAlpha(isTopThree ? bannerAccent : ACCENT_MAGENTA, 0.18)}, transparent 90%)`,
        }}
      />
      {index === 0 && (
        <div
          className="queue-item-top-edge"
          style={{ background: `linear-gradient(90deg, transparent, ${bannerAccent}, transparent)` }}
        />
      )}
      <div
        className="queue-item-rank"
        style={{
          background: isTopThree ? rankColor : 'transparent',
          color: isTopThree ? '#000' : 'rgba(255,255,255,0.35)',
          border: isTopThree ? 'none' : '1px solid rgba(255,255,255,0.1)',
          boxShadow: index === 0 ? `0 0 18px ${withAlpha(bannerAccent, 0.6)}` : 'none',
        }}
      >
        {index + 1}
      </div>
      {item.artwork_url ? (
        <img src={item.artwork_url} alt={item.title} className="queue-item-art" />
      ) : (
        <div className="queue-item-placeholder">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" xmlns="http://www.w3.org/2000/svg">
            <path d="M20 4v8.5a3.5 3.5 0 1 1-2-3.163V6l-9 1.5v9a3.5 3.5 0 1 1-2-3.163V5l13-1Z" />
          </svg>
        </div>
      )}
      <div className="queue-item-info">
        <div className="queue-item-title">{item.title}</div>
        <div className="queue-item-artist">{item.artist}</div>
        {item.nickname && <div className="queue-item-nickname">@{item.nickname}</div>}
      </div>
      <div className="queue-item-votes">
        <span
          className="queue-item-vote-num"
          style={{
            color: isTopThree ? rankColor : '#fff',
            textShadow: index === 0 ? `0 0 20px ${withAlpha(bannerAccent, 0.6)}` : 'none',
          }}
        >
          {item.vote_count}
        </span>
        <span className="queue-item-vote-label">VOTES</span>
      </div>
    </div>
  );
}
