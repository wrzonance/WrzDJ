'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams } from 'next/navigation';
import { api, ApiError, KioskDisplay, NowPlayingInfo } from '@/lib/api';
import { useEventStream } from '@/lib/use-event-stream';

export default function StreamOverlayPage() {
  const params = useParams();
  const code = params.code as string;

  const [display, setDisplay] = useState<KioskDisplay | null>(null);
  const [nowPlaying, setNowPlaying] = useState<NowPlayingInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ message: string; status: number } | null>(null);

  // Sticky now-playing: keep showing last track for 10s after it goes null
  const [lastKnownNowPlaying, setLastKnownNowPlaying] = useState<NowPlayingInfo | null>(null);
  const staleTimerRef = useRef<NodeJS.Timeout | null>(null);

  const loadData = useCallback(async (): Promise<boolean> => {
    try {
      const [kioskData, nowPlayingData] = await Promise.all([
        api.getKioskDisplay(code),
        api.getNowPlaying(code).catch((): undefined => undefined),
      ]);
      setDisplay(kioskData);
      // Only update now-playing when the fetch succeeded;
      // on transient network errors (undefined), preserve the previous value
      if (nowPlayingData !== undefined) {
        setNowPlaying(nowPlayingData);
      }
      setError(null);
      return true;
    } catch (err) {
      if (err instanceof ApiError) {
        setError({ message: err.message, status: err.status });
        if (err.status === 404 || err.status === 410) {
          return false;
        }
      } else {
        setError({ message: 'Event not found or expired', status: 0 });
      }
      return true;
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => {
    let intervalId: NodeJS.Timeout | null = null;
    let stopped = false;

    const poll = async () => {
      const shouldContinue = await loadData();
      if (!shouldContinue) {
        stopped = true;
        if (intervalId) {
          clearInterval(intervalId);
          intervalId = null;
        }
      }
    };

    poll();

    intervalId = setInterval(() => {
      if (!stopped) {
        poll();
      }
    }, 10_000);

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [loadData]);

  // SSE: trigger immediate refresh on any real-time event
  const loadDataRef = useRef(loadData);
  loadDataRef.current = loadData;
  useEventStream(code, {
    onNowPlayingChanged: () => { loadDataRef.current(); },
    onRequestStatusChanged: () => { loadDataRef.current(); },
    onRequestsBulkUpdate: () => { loadDataRef.current(); },
  });

  // Sticky now-playing effect
  useEffect(() => {
    if (nowPlaying) {
      if (staleTimerRef.current) {
        clearTimeout(staleTimerRef.current);
        staleTimerRef.current = null;
      }
      setLastKnownNowPlaying(nowPlaying);
    } else if (lastKnownNowPlaying) {
      if (!staleTimerRef.current) {
        staleTimerRef.current = setTimeout(() => {
          staleTimerRef.current = null;
          setLastKnownNowPlaying(null);
        }, 10_000);
      }
    }
  }, [nowPlaying, lastKnownNowPlaying]);

  useEffect(() => {
    return () => {
      if (staleTimerRef.current) {
        clearTimeout(staleTimerRef.current);
      }
    };
  }, []);

  if (loading) {
    return null;
  }

  if (error || !display) {
    return null;
  }

  const isHidden = display.now_playing_hidden;
  // Use sticky (lastKnownNowPlaying) instead of raw nowPlaying to avoid flickering
  const stickyNowPlaying = lastKnownNowPlaying ?? nowPlaying;
  const activeTrack = isHidden ? null : (stickyNowPlaying || (display.now_playing ? {
    title: display.now_playing.title,
    artist: display.now_playing.artist,
    album_art_url: display.now_playing.artwork_url,
    source: 'request',
  } : null));
  const isLive = stickyNowPlaying?.source != null && stickyNowPlaying.source !== 'manual';
  const upNext = display.accepted_queue.slice(0, 5);

  return (
    <>
      <style jsx global>{`
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body {
          overflow: hidden;
          font-family: var(--font-body, 'DM Sans'), -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        @keyframes pulse-live {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
      `}</style>

      <div style={{
        maxWidth: '400px',
        background: 'transparent',
        borderRadius: '12px',
        overflow: 'hidden',
        color: '#fff',
      }}>
        {/* Now Playing Section */}
        {activeTrack && (
          <div style={{ padding: '16px', borderBottom: upNext.length > 0 ? '1px solid rgba(255,255,255,0.1)' : 'none' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              marginBottom: '10px',
              fontSize: '11px',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: '#22c55e',
              fontWeight: 600,
              fontFamily: "var(--font-display, 'Plus Jakarta Sans'), -apple-system, sans-serif",
            }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 18V5l12-2v13" />
                <circle cx="6" cy="18" r="3" />
                <circle cx="18" cy="16" r="3" />
              </svg>
              NOW PLAYING
              {isLive && (
                <span style={{
                  background: '#ef4444',
                  color: '#fff',
                  fontSize: '9px',
                  padding: '1px 6px',
                  borderRadius: '3px',
                  fontWeight: 700,
                  marginLeft: '4px',
                  animation: 'pulse-live 2s ease-in-out infinite',
                }}>
                  LIVE
                </span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              {activeTrack.album_art_url ? (
                <img
                  src={activeTrack.album_art_url}
                  alt={activeTrack.title}
                  style={{
                    width: '64px',
                    height: '64px',
                    borderRadius: '8px',
                    objectFit: 'cover',
                    flexShrink: 0,
                  }}
                />
              ) : (
                <div style={{
                  width: '64px',
                  height: '64px',
                  borderRadius: '8px',
                  background: 'rgba(255,255,255,0.1)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  color: 'rgba(255,255,255,0.4)',
                }}>
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 18V5l12-2v13" />
                    <circle cx="6" cy="18" r="3" />
                    <circle cx="18" cy="16" r="3" />
                  </svg>
                </div>
              )}
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{
                  fontSize: '15px',
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}>
                  {activeTrack.title}
                </div>
                <div style={{
                  fontSize: '13px',
                  color: 'var(--text-secondary)',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  marginTop: '2px',
                }}>
                  {activeTrack.artist}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* No track playing placeholder */}
        {!activeTrack && upNext.length > 0 && (
          <div style={{
            padding: '16px',
            borderBottom: '1px solid rgba(255,255,255,0.1)',
            textAlign: 'center',
            color: '#6b7280',
            fontSize: '13px',
          }}>
            No track playing
          </div>
        )}

        {/* Up Next Section */}
        {upNext.length > 0 && (
          <div style={{ padding: '12px 16px 16px' }}>
            <div style={{
              fontSize: '11px',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: '#3b82f6',
              fontWeight: 600,
              fontFamily: "var(--font-display, 'Plus Jakarta Sans'), -apple-system, sans-serif",
              marginBottom: '8px',
            }}>
              IN QUEUE
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {upNext.map((item, index) => (
                <div key={item.id} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '6px 8px',
                  background: 'rgba(255,255,255,0.05)',
                  borderRadius: '6px',
                }}>
                  <span style={{
                    fontSize: '11px',
                    color: '#6b7280',
                    width: '16px',
                    textAlign: 'center',
                    flexShrink: 0,
                  }}>
                    {index + 1}
                  </span>
                  {item.artwork_url ? (
                    <img
                      src={item.artwork_url}
                      alt={item.title}
                      style={{
                        width: '32px',
                        height: '32px',
                        borderRadius: '4px',
                        objectFit: 'cover',
                        flexShrink: 0,
                      }}
                    />
                  ) : (
                    <div style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: '4px',
                      background: 'rgba(255,255,255,0.08)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                      color: 'rgba(255,255,255,0.3)',
                    }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 18V5l12-2v13" />
                        <circle cx="6" cy="18" r="3" />
                        <circle cx="18" cy="16" r="3" />
                      </svg>
                    </div>
                  )}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{
                      fontSize: '13px',
                      fontWeight: 500,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      color: '#e5e7eb',
                    }}>
                      {item.title}
                    </div>
                    <div style={{
                      fontSize: '11px',
                      color: 'var(--text-secondary)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}>
                      {item.artist}
                    </div>
                  </div>
                  {item.vote_count > 0 && (
                    <span style={{
                      fontSize: '10px',
                      color: '#60a5fa',
                      background: 'rgba(59, 130, 246, 0.15)',
                      padding: '2px 6px',
                      borderRadius: '8px',
                      whiteSpace: 'nowrap',
                      flexShrink: 0,
                    }}>
                      {item.vote_count}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty state — nothing playing and no queue */}
        {!activeTrack && upNext.length === 0 && (
          <div style={{
            padding: '24px 16px',
            textAlign: 'center',
            color: '#6b7280',
            fontSize: '13px',
          }}>
            No upcoming requests
          </div>
        )}
      </div>
    </>
  );
}
