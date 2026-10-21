'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { RequestModal } from './components/RequestModal';
import { AcceptedQueue } from './components/AcceptedQueue';
import { KioskDisplayStyles } from './components/KioskDisplayStyles';
import { KioskRequestStyles } from './components/KioskRequestStyles';
import { KioskRequestAccess } from './components/KioskRequestAccess';
import { ACCENT_CYAN, ACCENT_MAGENTA, safeColor, withAlpha } from './displayColors';
import { useKioskSessionLifecycle } from './useKioskSessionLifecycle';
import { useKioskDisplayData } from './useKioskDisplayData';

export default function KioskDisplayPage() {
  const params = useParams();
  const code = params.code as string;
  useKioskSessionLifecycle();

  const {
    display,
    loading,
    error,
    stagelinqNowPlaying,
    playHistory,
    lastKnownNowPlaying,
    nowPlayingFading,
    loadDisplay,
  } = useKioskDisplayData(code);

  // Request modal state
  const [showRequestModal, setShowRequestModal] = useState(false);

  if (loading) {
    return (
      <div className="kiosk-container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  if (error || !display) {
    const is410 = error?.status === 410;
    const is404 = error?.status === 404;

    return (
      <div className="kiosk-container">
        <div className="kiosk-error">
          <h1>{is410 ? 'Event Expired' : is404 ? 'Event Not Found' : 'Error'}</h1>
          <p>
            {is410
              ? 'This event has ended and is no longer accepting requests.'
              : is404
                ? 'This event does not exist.'
                : error?.message || 'This event may have expired.'}
          </p>
        </div>
      </div>
    );
  }

  const bannerAccent = safeColor(display.banner_colors?.[0], '#3b82f6');
  const acceptedTotal = display.accepted_queue_total;
  const totalVotes = display.accepted_queue.reduce((sum, item) => sum + item.vote_count, 0);

  // Resolve now-playing with sticky behavior
  const isHidden = display.now_playing_hidden;
  const stickyNowPlaying = lastKnownNowPlaying ?? stagelinqNowPlaying;
  const nowPlaying = isHidden ? null : (stickyNowPlaying || (display.now_playing ? {
    title: display.now_playing.title,
    artist: display.now_playing.artist,
    album_art_url: display.now_playing.artwork_url,
    source: 'request',
  } : null));
  const isLive = stickyNowPlaying?.source != null && stickyNowPlaying.source !== 'manual' && stickyNowPlaying.source !== 'request';

  // BPM/key from request-based now playing (bridge source doesn't expose these)
  const nowPlayingBpm = display.now_playing?.bpm;
  const nowPlayingKey = display.now_playing?.musical_key;

  return (
    <>
      <KioskDisplayStyles />
      <KioskRequestStyles />

      <div
        className="kiosk-container"
        style={display.banner_colors ? {
          '--kiosk-bg': display.banner_kiosk_url
            ? safeColor(display.banner_colors[0], '#1a1a2e')
            : `linear-gradient(135deg, ${safeColor(display.banner_colors[0], '#1a1a2e')} 0%, ${safeColor(display.banner_colors[1], '#16213e')} 50%, ${safeColor(display.banner_colors[2], '#0f3460')} 100%)`,
        } as React.CSSProperties : undefined}
      >
        {/* Banner background with gradient fade */}
        {display.banner_kiosk_url && (
          <div className="kiosk-banner-bg">
            <img
              src={display.banner_kiosk_url}
              alt=""
              onError={(e) => {
                const parent = e.currentTarget.parentElement;
                if (parent) parent.style.display = 'none';
              }}
            />
            <div className="kiosk-banner-fade" />
          </div>
        )}

        {/* Header */}
        <div className="kiosk-header">
          <div className="kiosk-header-left">
            <div className="kiosk-live-label">
              <span className="kiosk-live-dot" />
              LIVE &middot; WRZDJ
            </div>
            <h1 className="kiosk-event-name">{display.event.name}</h1>
            <div className="kiosk-stats">
              <div className="kiosk-stat">
                <span className="kiosk-stat-value">{acceptedTotal}</span>
                <span className="kiosk-stat-label">QUEUE</span>
              </div>
              <div className="kiosk-stat">
                <span className="kiosk-stat-value" style={{ color: bannerAccent }}>{totalVotes}</span>
                <span className="kiosk-stat-label">VOTES</span>
              </div>
            </div>
          </div>
          <KioskRequestAccess
            requestsOpen={display.requests_open}
            joinUrl={display.qr_join_url}
          />
        </div>

        {/* Main 3-column grid */}
        <div className={`kiosk-main ${nowPlaying ? '' : 'kiosk-main-single'}`}>
          {/* NOW PLAYING */}
          {nowPlaying && (
            <div className={`kiosk-panel now-playing-section ${nowPlayingFading ? 'fading' : ''}`}>
              <div className="kiosk-panel-label" style={{ color: ACCENT_CYAN }}>
                <span className="kiosk-live-dot" style={{
                  width: 7,
                  height: 7,
                  background: ACCENT_CYAN,
                  boxShadow: `0 0 10px ${ACCENT_CYAN}`,
                }} />
                NOW PLAYING
                {isLive && <span className="live-badge">LIVE</span>}
              </div>
              <div className="now-playing-content">
                {nowPlaying.album_art_url ? (
                  <img
                    src={nowPlaying.album_art_url}
                    alt={nowPlaying.title}
                    className="now-playing-art"
                  />
                ) : (
                  <div className="now-playing-placeholder">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" xmlns="http://www.w3.org/2000/svg">
                      <path d="M20 4v8.5a3.5 3.5 0 1 1-2-3.163V6l-9 1.5v9a3.5 3.5 0 1 1-2-3.163V5l13-1Z" />
                    </svg>
                  </div>
                )}
                <div style={{ textAlign: 'center', maxWidth: 320 }}>
                  <h2 className="now-playing-title">{nowPlaying.title}</h2>
                  <p className="now-playing-artist">{nowPlaying.artist}</p>
                </div>
                {(nowPlayingBpm || nowPlayingKey) && (
                  <div className="now-playing-chips">
                    {nowPlayingBpm && <span className="now-playing-chip">{nowPlayingBpm} BPM</span>}
                    {nowPlayingKey && <span className="now-playing-chip">KEY {nowPlayingKey}</span>}
                  </div>
                )}
                <div className="kiosk-eq-bars">
                  {Array.from({ length: 14 }, (_, i) => (
                    <div
                      key={i}
                      className="kiosk-eq-bar"
                      style={{
                        animation: `kiosk-eq ${0.6 + (i % 4) * 0.15}s ${i * 0.07}s infinite alternate ease-in-out`,
                      }}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}

          <AcceptedQueue
            items={display.accepted_queue}
            total={acceptedTotal}
            bannerAccent={bannerAccent}
            displayOnly={display.kiosk_display_only}
          />

          {/* RECENTLY PLAYED */}
          <div className="kiosk-panel">
            <div className="kiosk-panel-label" style={{ color: '#a78bfa' }}>
              RECENTLY PLAYED
            </div>
            {playHistory.length > 0 ? (
              <div className="history-list">
                {playHistory.map((item) => (
                  <div key={item.id} className="history-item">
                    {item.album_art_url ? (
                      <img src={item.album_art_url} alt={item.title} className="history-item-art" />
                    ) : (
                      <div className="history-item-placeholder">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" xmlns="http://www.w3.org/2000/svg">
                          <path d="M20 4v8.5a3.5 3.5 0 1 1-2-3.163V6l-9 1.5v9a3.5 3.5 0 1 1-2-3.163V5l13-1Z" />
                        </svg>
                      </div>
                    )}
                    <div className="history-item-info">
                      <div className="history-item-title">{item.title}</div>
                      <div className="history-item-artist">{item.artist}</div>
                    </div>
                    {item.matched_request_id && (
                      <span className="requested-badge">Requested</span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="history-empty">
                <p>No songs played yet.</p>
              </div>
            )}
          </div>
        </div>

        {/* CTA Button */}
        {!display.kiosk_display_only && display.requests_open && (
          <button
            className="request-button"
            onClick={() => setShowRequestModal(true)}
            style={{
              background: `linear-gradient(90deg, ${bannerAccent}, ${ACCENT_MAGENTA})`,
              boxShadow: `0 16px 50px ${withAlpha(bannerAccent, 0.5)}, 0 0 0 1px rgba(255,255,255,0.15) inset`,
            }}
          >
            <svg width="18" height="18" viewBox="0 0 14 14" fill="none">
              <path d="M7 1.5v11M1.5 7h11" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/>
            </svg>
            REQUEST A SONG
          </button>
        )}
      </div>

      {showRequestModal && (
        <RequestModal
          code={code}
          onClose={() => setShowRequestModal(false)}
          onRequestsClosed={() => loadDisplay()}
        />
      )}
    </>
  );
}
