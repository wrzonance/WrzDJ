'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { QRCodeSVG } from 'qrcode.react';
import { api, ApiError, KioskDisplay, NowPlayingInfo, PlayHistoryItem } from '@/lib/api';
import { useEventStream } from '@/lib/use-event-stream';
import { usePollingLoop } from '@/lib/usePollingLoop';
import { RequestModal } from './components/RequestModal';
const AUTO_SCROLL_INTERVAL = 5000; // 5 seconds between auto-scrolls
const SESSION_CHECK_INTERVAL = 10_000; // 10 seconds between kiosk session checks
const SESSION_TOKEN_KEY = 'kiosk_session_token';
const PAIR_CODE_KEY = 'kiosk_pair_code';
const HEX_COLOR_RE = /^#[0-9a-f]{6}$/i;
function safeColor(c: string | undefined, fallback: string): string {
  return c && HEX_COLOR_RE.test(c) ? c : fallback;
}

function withAlpha(hex: string, a: number): string {
  if (!hex || hex[0] !== '#') return hex;
  const h = hex.slice(1);
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

const ACCENT_CYAN = '#00f0ff';
const ACCENT_MAGENTA = '#ff2bd6';

export default function KioskDisplayPage() {
  const params = useParams();
  const router = useRouter();
  const code = params.code as string;

  const [display, setDisplay] = useState<KioskDisplay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ message: string; status: number } | null>(null);

  // StageLinQ data
  const [stagelinqNowPlaying, setStagelinqNowPlaying] = useState<NowPlayingInfo | null>(null);
  const [playHistory, setPlayHistory] = useState<PlayHistoryItem[]>([]);

  // Sticky now-playing: keep showing last track for 10s after it goes null
  const [lastKnownNowPlaying, setLastKnownNowPlaying] = useState<NowPlayingInfo | null>(null);
  const [nowPlayingFading, setNowPlayingFading] = useState(false);
  const staleTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Track previous accepted queue IDs for animation
  const prevAcceptedIdsRef = useRef<Set<number>>(new Set());
  const [newItemIds, setNewItemIds] = useState<Set<number>>(new Set());

  // Auto-scroll ref for display-only mode
  const queueListRef = useRef<HTMLDivElement>(null);

  // Request modal state
  const [showRequestModal, setShowRequestModal] = useState(false);

  // Track whether initial load succeeded (ref avoids stale closure in useCallback)
  const hasLoadedRef = useRef(false);

  // Load kiosk display data and StageLinQ data
  const loadDisplay = useCallback(async (): Promise<boolean> => {
    try {
      const [kioskData, nowPlayingData, historyData] = await Promise.all([
        api.getKioskDisplay(code),
        api.getNowPlaying(code).catch((): undefined => undefined),
        api.getPlayHistory(code).catch((): undefined => undefined),
      ]);
      setDisplay(kioskData);
      // Only update stagelinq now-playing when the fetch succeeded;
      // on transient network errors (undefined), preserve the previous value
      if (nowPlayingData !== undefined) {
        setStagelinqNowPlaying(nowPlayingData);
      }
      if (historyData !== undefined) {
        setPlayHistory(historyData.items);
      }
      setError(null);
      hasLoadedRef.current = true;
      return true; // Continue polling
    } catch (err) {
      if (err instanceof ApiError) {
        // Only show error UI on terminal errors or if we have no display data yet;
        // on transient errors with existing data, silently retry to avoid flickering
        if (err.status === 404 || err.status === 410) {
          setError({ message: err.message, status: err.status });
          return false;
        }
      }
      // For transient errors: only set error if this is the initial load (no data yet)
      if (!hasLoadedRef.current) {
        setError({ message: 'Event not found or expired', status: 0 });
      }
      return true; // Continue polling for transient errors
    } finally {
      setLoading(false);
    }
  }, [code]);

  // Poll every 10s as fallback (SSE handles real-time updates).
  usePollingLoop(true, loadDisplay, 10_000);

  // SSE: trigger immediate refresh on any real-time event
  const loadDisplayRef = useRef(loadDisplay);
  loadDisplayRef.current = loadDisplay;
  useEventStream(code, {
    onRequestCreated: () => { loadDisplayRef.current(); },
    onRequestStatusChanged: () => { loadDisplayRef.current(); },
    onNowPlayingChanged: () => { loadDisplayRef.current(); },
    onRequestsBulkUpdate: () => { loadDisplayRef.current(); },
    onBridgeStatusChanged: () => { loadDisplayRef.current(); },
  });

  // Check kiosk session validity — detect unpair
  useEffect(() => {
    const token = typeof window !== 'undefined'
      ? localStorage.getItem(SESSION_TOKEN_KEY)
      : null;
    if (!token) return;

    const checkSession = async () => {
      try {
        const assignment = await api.getKioskAssignment(token);
        // A 200 can still be terminal: the assigned event was deleted (legacy/
        // edge orphan → 'unassigned') or the pairing lapsed ('expired'). Both
        // mean this device must re-pair (issue #474).
        if (assignment.status === 'unassigned' || assignment.status === 'expired') {
          localStorage.removeItem(SESSION_TOKEN_KEY);
          localStorage.removeItem(PAIR_CODE_KEY);
          router.push('/kiosk-pair');
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          localStorage.removeItem(SESSION_TOKEN_KEY);
          localStorage.removeItem(PAIR_CODE_KEY);
          router.push('/kiosk-pair');
        }
        // Other errors (network, 500, etc.) — silently ignore
      }
    };

    const intervalId = setInterval(checkSession, SESSION_CHECK_INTERVAL);
    return () => clearInterval(intervalId);
  }, [router]);

  // Sticky now-playing effect
  useEffect(() => {
    if (stagelinqNowPlaying) {
      // New data arrived — show it immediately, cancel any pending fade
      if (staleTimerRef.current) {
        clearTimeout(staleTimerRef.current);
        staleTimerRef.current = null;
      }
      setLastKnownNowPlaying(stagelinqNowPlaying);
      setNowPlayingFading(false);
    } else if (lastKnownNowPlaying) {
      // Data went null — start 10s grace, then clear
      if (!staleTimerRef.current) {
        setNowPlayingFading(true);
        staleTimerRef.current = setTimeout(() => {
          staleTimerRef.current = null;
          setLastKnownNowPlaying(null);
          setNowPlayingFading(false);
        }, 10_000);
      }
    }
  }, [stagelinqNowPlaying, lastKnownNowPlaying]);

  // Cleanup stale timer on unmount
  useEffect(() => {
    return () => {
      if (staleTimerRef.current) {
        clearTimeout(staleTimerRef.current);
      }
    };
  }, []);

  // Kiosk mode protections
  useEffect(() => {
    const preventDefaults = (e: Event) => {
      e.preventDefault();
      return false;
    };
    document.addEventListener('contextmenu', preventDefaults);
    document.addEventListener('selectstart', preventDefaults);
    document.addEventListener('dragstart', preventDefaults);
    return () => {
      document.removeEventListener('contextmenu', preventDefaults);
      document.removeEventListener('selectstart', preventDefaults);
      document.removeEventListener('dragstart', preventDefaults);
    };
  }, []);

  // Detect newly accepted items for animation
  useEffect(() => {
    if (!display) return;
    const currentIds = new Set(display.accepted_queue.map((item) => item.id));
    const prev = prevAcceptedIdsRef.current;

    // Find IDs that are in current but not in previous
    const fresh = new Set<number>();
    for (const id of currentIds) {
      if (!prev.has(id)) fresh.add(id);
    }

    if (fresh.size > 0) {
      setNewItemIds(fresh);
      // Remove animation class after animation completes
      const timer = setTimeout(() => setNewItemIds(new Set()), 800);
      prevAcceptedIdsRef.current = currentIds;
      return () => clearTimeout(timer);
    }

    prevAcceptedIdsRef.current = currentIds;
  }, [display?.accepted_queue]);

  // Auto-scroll queue list in display-only mode
  useEffect(() => {
    if (!display?.kiosk_display_only) return;

    const interval = setInterval(() => {
      const el = queueListRef.current;
      if (!el) return;

      // If near the bottom, scroll back to top
      if (el.scrollTop + el.clientHeight >= el.scrollHeight - 10) {
        el.scrollTo({ top: 0, behavior: 'smooth' });
      } else {
        el.scrollBy({ top: 85, behavior: 'smooth' });
      }
    }, AUTO_SCROLL_INTERVAL);

    return () => clearInterval(interval);
  }, [display?.kiosk_display_only]);

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
  const queue = display.accepted_queue;
  const maxVotes = Math.max(1, ...queue.map((r) => r.vote_count));
  const totalVotes = queue.reduce((s, r) => s + r.vote_count, 0);

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
      <style jsx global>{`
        * {
          user-select: none;
          -webkit-user-select: none;
          -webkit-touch-callout: none;
          cursor: none;
        }
        body {
          overflow: hidden;
          margin: 0;
        }

        /* ── Container ── */
        .kiosk-container {
          height: 100vh;
          background: var(--kiosk-bg, linear-gradient(135deg, #1a1a2e 0%, #16213e 100%));
          padding: 40px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          position: relative;
          font-family: var(--font-display, 'Plus Jakarta Sans'), system-ui, sans-serif;
          color: #fff;
        }

        /* ── Banner background with fade ── */
        .kiosk-banner-bg {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          height: 60%;
          z-index: 0;
          overflow: hidden;
          pointer-events: none;
        }
        .kiosk-banner-bg img {
          width: 100%;
          height: 100%;
          object-fit: cover;
          display: block;
          filter: saturate(0.55) brightness(0.7);
        }
        .kiosk-banner-fade {
          position: absolute;
          inset: 0;
          background: linear-gradient(180deg, transparent 0%, transparent 30%, var(--kiosk-bg, #1a1a2e) 100%);
        }

        /* ── Header ── */
        .kiosk-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 32px;
          position: relative;
          z-index: 1;
        }
        .kiosk-live-label {
          font-family: var(--font-mono, 'JetBrains Mono'), ui-monospace, monospace;
          font-size: 16px;
          letter-spacing: 4px;
          color: ${withAlpha(ACCENT_CYAN, 0.9)};
          font-weight: 700;
          text-transform: uppercase;
          margin-bottom: 12px;
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .kiosk-live-dot {
          display: inline-block;
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: ${ACCENT_CYAN};
          box-shadow: 0 0 14px ${ACCENT_CYAN};
          animation: kiosk-pulse 1.6s ease-in-out infinite;
        }
        .kiosk-header-left {
          flex: 1;
          min-width: 0;
        }
        .kiosk-event-name {
          font-size: 76px;
          font-weight: 800;
          letter-spacing: -2.4px;
          line-height: 1;
          margin: 0;
          text-shadow: 0 4px 30px rgba(0,0,0,0.5);
          font-family: var(--font-display, 'Plus Jakarta Sans'), -apple-system, sans-serif;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .kiosk-stats {
          display: flex;
          gap: 12px;
          margin-top: 22px;
        }
        .kiosk-stat {
          padding: 10px 18px;
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,0.1);
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          min-width: 80px;
          background: rgba(0,0,0,0.2);
        }
        .kiosk-stat-value {
          font-family: var(--font-mono, 'JetBrains Mono'), monospace;
          font-size: 26px;
          font-weight: 800;
          line-height: 1;
          font-variant-numeric: tabular-nums;
        }
        .kiosk-stat-label {
          font-family: var(--font-mono, 'JetBrains Mono'), monospace;
          font-size: 11px;
          color: rgba(255,255,255,0.55);
          letter-spacing: 1.8px;
          margin-top: 6px;
          font-weight: 600;
        }
        .kiosk-closed-banner {
          background: rgba(239, 68, 68, 0.35);
          border: 2px solid rgba(239, 68, 68, 0.5);
          color: #fca5a5;
          padding: 1rem 2rem;
          border-radius: 1rem;
          font-size: 1.25rem;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.1em;
        }
        .kiosk-qr {
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .kiosk-qr-bg {
          background: #fff;
          padding: 12px;
          border-radius: 14px;
        }
        .kiosk-qr-label {
          font-size: 14px;
          font-weight: 600;
          color: #fff;
          margin-top: 10px;
          text-align: center;
          max-width: 160px;
          letter-spacing: 0.2px;
        }

        /* ── 3-column grid ── */
        .kiosk-main {
          flex: 1;
          display: grid;
          grid-template-columns: 1fr 1.3fr 1fr;
          gap: 28px;
          min-height: 0;
          position: relative;
          z-index: 1;
        }
        .kiosk-main-single {
          grid-template-columns: 1.3fr 1fr;
        }

        /* ── Glass panels ── */
        .kiosk-panel {
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 24px;
          padding: 26px;
          display: flex;
          flex-direction: column;
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          min-height: 0;
          position: relative;
          overflow: hidden;
        }
        .kiosk-panel-label {
          font-family: var(--font-mono, 'JetBrains Mono'), monospace;
          font-size: 14px;
          font-weight: 700;
          letter-spacing: 2.4px;
          text-transform: uppercase;
          margin-bottom: 18px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        /* ── Now Playing ── */
        .now-playing-section {
          transition: opacity 1s ease-out;
        }
        .now-playing-section.fading {
          opacity: 0.5;
        }
        .now-playing-content {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 24px;
        }
        .now-playing-art {
          width: 240px;
          height: 240px;
          border-radius: 16px;
          object-fit: cover;
          box-shadow: 0 12px 32px rgba(0,0,0,0.45);
          flex-shrink: 0;
        }
        .now-playing-placeholder {
          width: 240px;
          height: 240px;
          border-radius: 16px;
          background: rgba(255,255,255,0.08);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          box-shadow: 0 12px 32px rgba(0,0,0,0.45);
        }
        .now-playing-title {
          font-size: 32px;
          font-weight: 800;
          letter-spacing: -0.6px;
          line-height: 1.1;
          text-align: center;
          margin: 0;
          max-width: 320px;
          overflow: hidden;
          text-overflow: ellipsis;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }
        .now-playing-artist {
          font-size: 22px;
          color: rgba(255,255,255,0.55);
          text-align: center;
          margin: 0;
        }
        .now-playing-chips {
          display: flex;
          gap: 14px;
        }
        .now-playing-chip {
          padding: 6px 12px;
          border-radius: 99px;
          border: 1px solid rgba(255,255,255,0.1);
          font-family: var(--font-mono, 'JetBrains Mono'), monospace;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 1.2px;
          color: rgba(255,255,255,0.55);
        }

        .live-badge {
          background: #ef4444;
          color: #fff;
          font-size: 0.65rem;
          padding: 0.2rem 0.5rem;
          border-radius: 0.25rem;
          font-weight: bold;
          animation: kiosk-pulse 2s ease-in-out infinite;
          margin-left: 4px;
        }

        /* ── EQ Bars ── */
        .kiosk-eq-bars {
          display: flex;
          align-items: flex-end;
          gap: 4px;
          height: 56px;
        }
        .kiosk-eq-bar {
          width: 6px;
          height: 40%;
          border-radius: 3px;
          background: linear-gradient(to top, ${ACCENT_CYAN}, ${withAlpha(ACCENT_CYAN, 0.6)});
          transform-origin: bottom;
        }

        /* ── Queue ── */
        .queue-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 18px;
        }
        .queue-track-count {
          font-family: var(--font-mono, 'JetBrains Mono'), monospace;
          font-size: 12px;
          color: rgba(255,255,255,0.35);
          letter-spacing: 2px;
        }
        .queue-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          overflow-y: auto;
          flex: 1;
          min-height: 0;
        }
        .queue-list::-webkit-scrollbar {
          width: 4px;
        }
        .queue-list::-webkit-scrollbar-track {
          background: transparent;
        }
        .queue-list::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.15);
          border-radius: 2px;
        }
        .queue-item {
          position: relative;
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 14px;
          padding: 12px 16px;
          display: flex;
          align-items: center;
          gap: 14px;
          overflow: hidden;
        }
        .queue-item-top1 {
          border-color: var(--banner-accent-50, rgba(255,255,255,0.1));
          box-shadow: 0 0 0 1px var(--banner-accent-30, transparent), 0 8px 32px var(--banner-accent-20, transparent);
        }
        .queue-item-top-edge {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          height: 1px;
        }
        .queue-item-vote-bar {
          position: absolute;
          left: 0;
          top: 0;
          bottom: 0;
          pointer-events: none;
        }
        .queue-item-rank {
          position: relative;
          z-index: 1;
          width: 42px;
          height: 42px;
          flex-shrink: 0;
          border-radius: 10px;
          font-family: var(--font-mono, 'JetBrains Mono'), monospace;
          font-weight: 800;
          font-size: 18px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .queue-item-art {
          width: 50px;
          height: 50px;
          border-radius: 8px;
          object-fit: cover;
          flex-shrink: 0;
          position: relative;
          z-index: 1;
        }
        .queue-item-placeholder {
          width: 50px;
          height: 50px;
          border-radius: 8px;
          background: rgba(255,255,255,0.08);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          position: relative;
          z-index: 1;
        }
        .queue-item-info {
          flex: 1;
          min-width: 0;
          position: relative;
          z-index: 1;
        }
        .queue-item-title {
          font-size: 22px;
          font-weight: 700;
          letter-spacing: -0.3px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .queue-item-artist {
          font-size: 17px;
          color: rgba(255,255,255,0.55);
          margin-top: 2px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .queue-item-nickname {
          font-size: 12px;
          color: rgba(255,255,255,0.35);
          margin-top: 4px;
          font-family: var(--font-mono, 'JetBrains Mono'), monospace;
          letter-spacing: 0.5px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .queue-item-votes {
          position: relative;
          z-index: 1;
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          flex-shrink: 0;
        }
        .queue-item-vote-num {
          font-family: var(--font-mono, 'JetBrains Mono'), monospace;
          font-weight: 800;
          font-size: 28px;
          line-height: 1;
          font-variant-numeric: tabular-nums;
        }
        .queue-item-vote-label {
          font-family: var(--font-mono, 'JetBrains Mono'), monospace;
          font-size: 10px;
          color: rgba(255,255,255,0.35);
          letter-spacing: 2px;
          margin-top: 4px;
        }
        .queue-item-new {
          animation: slide-in-glow 0.8s ease-out;
        }
        .queue-empty {
          color: rgba(255,255,255,0.35);
          text-align: center;
          padding: 2rem;
          font-size: 18px;
        }

        /* ── History ── */
        .history-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
          overflow-y: auto;
          flex: 1;
          min-height: 0;
        }
        .history-list::-webkit-scrollbar {
          width: 4px;
        }
        .history-list::-webkit-scrollbar-track {
          background: transparent;
        }
        .history-list::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.15);
          border-radius: 2px;
        }
        .history-item {
          background: rgba(255,255,255,0.06);
          border-radius: 12px;
          padding: 10px 12px;
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .history-item-art {
          width: 44px;
          height: 44px;
          border-radius: 8px;
          object-fit: cover;
          flex-shrink: 0;
        }
        .history-item-placeholder {
          width: 44px;
          height: 44px;
          border-radius: 8px;
          background: rgba(255,255,255,0.06);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .history-item-info {
          flex: 1;
          min-width: 0;
        }
        .history-item-title {
          font-size: 17px;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .history-item-artist {
          font-size: 14px;
          color: rgba(255,255,255,0.55);
          margin-top: 1px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .history-empty {
          color: rgba(255,255,255,0.35);
          text-align: center;
          padding: 2rem;
        }
        .requested-badge {
          background: #22c55e;
          color: #fff;
          font-size: 0.65rem;
          padding: 0.2rem 0.5rem;
          border-radius: 0.25rem;
          white-space: nowrap;
          flex-shrink: 0;
        }

        /* ── CTA Button ── */
        .request-button {
          margin-top: 28px;
          align-self: center;
          flex-shrink: 0;
          position: relative;
          z-index: 1;
          border: none;
          color: #0a0a0a;
          font-family: var(--font-display, 'Plus Jakarta Sans'), sans-serif;
          font-size: 22px;
          font-weight: 800;
          letter-spacing: 0.5px;
          padding: 20px 56px;
          border-radius: 999px;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 12px;
          transition: transform 0.2s, box-shadow 0.2s;
        }
        .request-button:hover {
          transform: scale(1.05);
        }
        .request-button:active {
          transform: scale(0.98);
        }

        /* ── Animations ── */
        @keyframes kiosk-eq {
          from { height: 18%; }
          to { height: 100%; }
        }
        @keyframes kiosk-pulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.4); opacity: 0.7; }
        }
        @keyframes slide-in-glow {
          0% {
            transform: translateX(-30px);
            opacity: 0;
            box-shadow: 0 0 0 0 rgba(34, 197, 94, 0);
          }
          30% {
            opacity: 1;
            box-shadow: 0 0 20px 4px rgba(34, 197, 94, 0.4);
          }
          100% {
            transform: translateX(0);
            box-shadow: 0 0 0 0 rgba(34, 197, 94, 0);
          }
        }

        /* ── Modal styles (used by RequestModal component) ── */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0,0,0,0.9);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 2rem;
        }
        .modal-content {
          background: #1f2937;
          border-radius: 1.5rem;
          padding: 2rem;
          width: 100%;
          max-width: 500px;
          max-height: 80vh;
          overflow-y: auto;
          transition: max-height 0.2s ease, margin-top 0.2s ease;
        }
        .modal-content.keyboard-active {
          max-width: 700px;
          max-height: 95vh;
          overflow-y: auto;
          padding: 1.25rem;
          padding-bottom: 280px;
        }
        .modal-overlay.keyboard-overlay-active {
          align-items: flex-start;
          padding-top: 1rem;
          padding-left: 1rem;
          padding-right: 1rem;
        }
        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 1.5rem;
        }
        .modal-title {
          font-size: 1.5rem;
          font-weight: bold;
          color: #fff;
          margin: 0;
        }
        .modal-close {
          background: transparent;
          border: none;
          color: #9ca3af;
          font-size: 2rem;
          cursor: pointer;
          line-height: 1;
        }
        .search-form {
          display: flex;
          gap: 0.5rem;
          margin-bottom: 1rem;
        }
        .search-input {
          flex: 1;
          background: #374151;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem;
          color: #fff;
          font-size: 1rem;
        }
        .search-button {
          background: #3b82f6;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem 1.5rem;
          color: #fff;
          font-weight: 500;
          cursor: pointer;
        }
        .search-results {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
          max-height: 300px;
          overflow-y: auto;
          transition: max-height 0.2s ease;
        }
        .search-results-compact {
          max-height: 50vh;
        }
        .search-result-item {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          background: #374151;
          padding: 0.75rem;
          border-radius: 0.5rem;
          border: none;
          cursor: pointer;
          text-align: left;
          width: 100%;
          color: #fff;
        }
        .search-result-item:hover {
          background: #4b5563;
        }
        .confirm-section {
          text-align: center;
        }
        .confirm-song {
          margin-bottom: 1.5rem;
        }
        .confirm-title {
          font-size: 1.25rem;
          font-weight: bold;
          color: #fff;
          margin: 0 0 0.25rem;
        }
        .confirm-artist {
          color: #9ca3af;
          margin: 0;
        }
        .note-input {
          width: 100%;
          background: #374151;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem;
          color: #fff;
          font-size: 1rem;
          margin-bottom: 1rem;
        }
        .confirm-buttons {
          display: flex;
          gap: 1rem;
        }
        .confirm-submit {
          flex: 1;
          background: #22c55e;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem;
          color: #fff;
          font-weight: bold;
          font-size: 1.1rem;
          cursor: pointer;
        }
        .confirm-back {
          background: #374151;
          border: none;
          border-radius: 0.5rem;
          padding: 1rem 1.5rem;
          color: #fff;
          cursor: pointer;
        }
        .success-message {
          text-align: center;
          padding: 2rem;
        }
        .success-icon {
          font-size: 4rem;
          margin-bottom: 1rem;
        }
        .success-text {
          font-size: 1.5rem;
          color: #22c55e;
          font-weight: bold;
        }
        .success-vote-count {
          color: #9ca3af;
          margin-top: 0.5rem;
        }
        .search-result-art {
          width: 48px;
          height: 48px;
          border-radius: 4px;
          object-fit: cover;
        }
        .search-result-placeholder {
          width: 48px;
          height: 48px;
          border-radius: 4px;
          background: rgba(255,255,255,0.1);
          display: flex;
          align-items: center;
          justify-content: center;
          color: rgba(255,255,255,0.5);
        }
        .search-result-info {
          flex: 1;
          min-width: 0;
        }
        .search-result-title {
          font-weight: 500;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .search-result-artist {
          color: #9ca3af;
          font-size: 0.875rem;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      `}</style>

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
                <span className="kiosk-stat-value">{queue.length}</span>
                <span className="kiosk-stat-label">QUEUE</span>
              </div>
              <div className="kiosk-stat">
                <span className="kiosk-stat-value" style={{ color: bannerAccent }}>{totalVotes}</span>
                <span className="kiosk-stat-label">VOTES</span>
              </div>
            </div>
          </div>
          {!display.requests_open ? (
            <div className="kiosk-closed-banner">
              Requests Closed
            </div>
          ) : (
            <div className="kiosk-qr">
              <div className="kiosk-qr-bg">
                <QRCodeSVG value={display.qr_join_url} size={140} />
              </div>
              <p className="kiosk-qr-label">Scan to request from phone</p>
            </div>
          )}
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

          {/* QUEUE (leaderboard) */}
          <div className="kiosk-panel">
            <div className="queue-header">
              <div className="kiosk-panel-label" style={{ color: ACCENT_MAGENTA, marginBottom: 0 }}>
                QUEUE
              </div>
              <div style={{ flex: 1 }} />
              <span className="queue-track-count">{queue.length} TRACKS</span>
            </div>
            {queue.length > 0 ? (
              <div className="queue-list" ref={queueListRef}>
                {queue.map((item, i) => {
                  const pct = maxVotes > 0 ? (item.vote_count / maxVotes) * 100 : 0;
                  const isTop3 = i < 3;
                  const rankColor = i === 0
                    ? bannerAccent
                    : i === 1
                      ? '#fff'
                      : i === 2
                        ? ACCENT_MAGENTA
                        : 'rgba(255,255,255,0.35)';

                  return (
                    <div
                      key={item.id}
                      className={`queue-item${i === 0 ? ' queue-item-top1' : ''}${newItemIds.has(item.id) ? ' queue-item-new' : ''}`}
                      style={i === 0 ? {
                        background: withAlpha(bannerAccent, 0.12),
                        '--banner-accent-50': withAlpha(bannerAccent, 0.5),
                        '--banner-accent-30': withAlpha(bannerAccent, 0.3),
                        '--banner-accent-20': withAlpha(bannerAccent, 0.2),
                      } as React.CSSProperties : undefined}
                    >
                      {/* Vote bar fill */}
                      <div
                        className="queue-item-vote-bar"
                        style={{
                          width: `${pct}%`,
                          background: `linear-gradient(90deg, ${withAlpha(isTop3 ? bannerAccent : ACCENT_MAGENTA, 0.18)}, transparent 90%)`,
                        }}
                      />
                      {/* Top-edge glow for #1 */}
                      {i === 0 && (
                        <div
                          className="queue-item-top-edge"
                          style={{
                            background: `linear-gradient(90deg, transparent, ${bannerAccent}, transparent)`,
                          }}
                        />
                      )}

                      {/* Rank badge */}
                      <div
                        className="queue-item-rank"
                        style={{
                          background: isTop3 ? rankColor : 'transparent',
                          color: isTop3 ? '#000' : 'rgba(255,255,255,0.35)',
                          border: isTop3 ? 'none' : '1px solid rgba(255,255,255,0.1)',
                          boxShadow: i === 0 ? `0 0 18px ${withAlpha(bannerAccent, 0.6)}` : 'none',
                        }}
                      >
                        {i + 1}
                      </div>

                      {/* Artwork */}
                      {item.artwork_url ? (
                        <img src={item.artwork_url} alt={item.title} className="queue-item-art" />
                      ) : (
                        <div className="queue-item-placeholder">
                          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" xmlns="http://www.w3.org/2000/svg">
                            <path d="M20 4v8.5a3.5 3.5 0 1 1-2-3.163V6l-9 1.5v9a3.5 3.5 0 1 1-2-3.163V5l13-1Z" />
                          </svg>
                        </div>
                      )}

                      {/* Track info */}
                      <div className="queue-item-info">
                        <div className="queue-item-title">{item.title}</div>
                        <div className="queue-item-artist">{item.artist}</div>
                        {item.nickname && (
                          <div className="queue-item-nickname">@{item.nickname}</div>
                        )}
                      </div>

                      {/* Vote count */}
                      <div className="queue-item-votes">
                        <span
                          className="queue-item-vote-num"
                          style={{
                            color: isTop3 ? rankColor : '#fff',
                            textShadow: i === 0 ? `0 0 20px ${withAlpha(bannerAccent, 0.6)}` : 'none',
                          }}
                        >
                          {item.vote_count}
                        </span>
                        <span className="queue-item-vote-label">VOTES</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="queue-empty">
                <p>No songs in queue yet.</p>
                <p>Be the first to request!</p>
              </div>
            )}
          </div>

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
