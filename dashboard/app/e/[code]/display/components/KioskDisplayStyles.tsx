'use client';

const ACCENT_CYAN = '#00f0ff';

function withAlpha(hex: string, alpha: number): string {
  const value = hex.slice(1);
  const red = parseInt(value.slice(0, 2), 16);
  const green = parseInt(value.slice(2, 4), 16);
  const blue = parseInt(value.slice(4, 6), 16);
  return `rgba(${red},${green},${blue},${alpha})`;
}

export function KioskDisplayStyles() {
  return <style jsx global>{`        * {
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
          /* Keep natural row height so a long accepted queue scrolls instead of
             squishing: overflow:hidden zeroes the flex auto min-height, so without
             flex-shrink:0 the column crushes every row to fit (issue #478). */
          flex-shrink: 0;
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

`}</style>;
}
