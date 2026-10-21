'use client';

import { useEffect, useState } from 'react';
import type { CollectLeaderboardRow, CollectPreviewResponse } from '@/lib/api';
import { api } from '@/lib/api';
import { getEmbedUrl, getPreviewSource } from '@/lib/preview-embed';
import { artGradient } from '@/lib/art-gradient';

interface Props {
  row: CollectLeaderboardRow;
  code: string;
  rank: number;
  totalCount: number;
  voted: boolean;
  voteError?: string | null;
  onVote: () => void;
  onClose: () => void;
  reverify?: () => Promise<void>;
}

const ACCENT = '#00f0ff';
const ACCENT2 = '#ff2bd6';

export default function CollectDetailSheet({
  row, code, rank, totalCount, voted, voteError, onVote, onClose, reverify,
}: Props) {
  const [isWide, setIsWide] = useState<boolean | null>(null);

  useEffect(() => {
    const check = () => setIsWide(window.innerWidth >= 640);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  const [preview, setPreview] = useState<CollectPreviewResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getCollectPreview(code, row.id, reverify).then((data) => {
      if (!cancelled) setPreview(data);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [code, row.id]);

  const surface = 'rgba(255,255,255,0.05)';
  const border = 'rgba(255,255,255,0.1)';
  const subFg = 'rgba(255,255,255,0.55)';
  const subFg2 = 'rgba(255,255,255,0.35)';
  const initials = `${row.title[0] ?? '?'}${row.artist[0] ?? ''}`.toUpperCase();

  const pills = (row.bpm || row.musical_key) ? (
    <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
      {row.bpm && (
        <span style={{
          fontFamily: 'var(--font-mono, monospace)', fontSize: 10.3, fontWeight: 700,
          padding: '3px 9px', borderRadius: 6,
          background: `${ACCENT}18`, border: `1px solid ${ACCENT}50`, color: ACCENT,
          letterSpacing: 1,
        }}>
          {row.bpm} BPM
        </span>
      )}
      {row.musical_key && (
        <span style={{
          fontFamily: 'var(--font-mono, monospace)', fontSize: 10.3, fontWeight: 700,
          padding: '3px 9px', borderRadius: 6,
          background: 'rgba(255,255,255,0.06)', border: `1px solid ${border}`,
          color: 'rgba(255,255,255,0.7)', letterSpacing: 1,
        }}>
          {row.musical_key}
        </span>
      )}
    </div>
  ) : null;

  const statsRow = (
    <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
      <div style={{ flex: 1, padding: 14, borderRadius: 14, background: surface, border: `1px solid ${border}`, textAlign: 'center' }}>
        <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10.3, color: subFg, letterSpacing: 1.5 }}>VOTES</div>
        <div style={{ fontSize: 30, fontWeight: 800, color: ACCENT, lineHeight: 1, marginTop: 4 }}>{row.vote_count}</div>
      </div>
      <div style={{ flex: 1, padding: 14, borderRadius: 14, background: surface, border: `1px solid ${border}`, textAlign: 'center' }}>
        <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10.3, color: subFg, letterSpacing: 1.5 }}>RANK</div>
        <div style={{ fontSize: 30, fontWeight: 800, color: '#fff', lineHeight: 1, marginTop: 4 }}>#{rank}</div>
        <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 9.7, color: subFg2, marginTop: 2 }}>of {totalCount}</div>
      </div>
    </div>
  );

  const voteBtn = (
    <button
      onClick={onVote}
      style={{
        width: '100%', height: 56, borderRadius: 14, marginTop: 12,
        background: voted ? 'transparent' : `linear-gradient(90deg, ${ACCENT}, ${ACCENT2})`,
        border: voted ? `1.5px solid ${ACCENT}` : 'none',
        color: voted ? ACCENT : 'var(--text-on-bright-accent)',
        fontFamily: 'var(--font-grotesk, system-ui)', fontSize: 16.9, fontWeight: 800,
        cursor: voted ? 'default' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
        transition: 'all 160ms',
        boxShadow: voted ? 'none' : `0 12px 32px -8px ${ACCENT}90`,
      }}
    >
      <svg width="12" height="12" viewBox="0 0 14 14" fill="none">
        <path d="M2 9L7 3L12 9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
      {voted ? 'VOTED' : 'UPVOTE THIS TRACK'}
    </button>
  );

  const suggestedBy = row.nickname ? (
    <div style={{
      marginTop: 12, padding: 12, borderRadius: 12,
      background: surface, border: `1px solid ${border}`,
      display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
        background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT2})`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 14, fontWeight: 800, color: 'var(--text-on-bright-accent)',
      }}>
        {row.nickname[0]?.toUpperCase() ?? '?'}
      </div>
      <div>
        <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 9.7, color: subFg, letterSpacing: 1.5 }}>SUGGESTED BY</div>
        <div style={{ fontSize: 16.4, fontWeight: 700, marginTop: 2 }}>{row.nickname}</div>
      </div>
    </div>
  ) : null;

  const header = (
    <div style={{ padding: '12px 16px 6px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10.3, color: subFg, letterSpacing: 1.5 }}>
        PRE-EVENT · #{rank}
      </div>
      <button
        onClick={onClose}
        style={{
          width: 40, height: 40, borderRadius: 11,
          background: surface, border: `1px solid ${border}`, color: '#fff',
          cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
        aria-label="Close"
      >
        <svg width="14" height="14" viewBox="0 0 14 14">
          <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
        </svg>
      </button>
    </div>
  );

  const previewSection = (() => {
    if (!preview || !preview.source_url) return null;

    const previewData = { source: preview.source, sourceUrl: preview.source_url };
    const embedUrl = getEmbedUrl(previewData);
    const source = getPreviewSource(previewData);

    if (embedUrl) {
      return (
        <div style={{ marginTop: 12 }}>
          <iframe
            src={embedUrl + (source === 'tidal' ? '?coverImageStyle=round&tracklist=false' : '')}
            title={`${row.title} by ${row.artist}`}
            width="100%"
            height={152}
            style={{ borderRadius: 14, border: 'none' }}
            allow="encrypted-media"
            loading="lazy"
          />
        </div>
      );
    }

    if (source === 'beatport') {
      return (
        <div style={{ marginTop: 12 }}>
          <a
            href={preview.source_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              width: '100%', height: 44, borderRadius: 12,
              background: surface, border: `1px solid ${border}`,
              fontFamily: 'var(--font-mono, monospace)', fontSize: 11, fontWeight: 700,
              color: 'rgba(255,255,255,0.7)', textDecoration: 'none', letterSpacing: 1,
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/>
            </svg>
            OPEN IN BEATPORT
          </a>
        </div>
      );
    }

    return null;
  })();

  if (isWide === null) return null;

  /* ── Desktop: centered dialog ─────────────────────────────── */
  if (isWide) {
    return (
      <div
        style={{
          position: 'fixed', inset: 0, zIndex: 110,
          background: 'var(--color-overlay)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: '20px',
          animation: 'cds-backdrop-in 220ms ease',
        }}
        onClick={onClose}
      >
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            width: '100%', maxWidth: 480, background: '#0f0f18',
            borderRadius: 20, border: `1px solid ${border}`,
            boxShadow: '0 40px 100px rgba(0,0,0,0.6)',
            fontFamily: 'var(--font-grotesk, system-ui)',
            color: '#fff', overflow: 'hidden',
            animation: 'cds-card-in 260ms cubic-bezier(.2,.8,.2,1)',
          }}
        >
          {header}
          {/* Art + title side by side */}
          <div style={{ display: 'flex', gap: 14, padding: '10px 16px 0', alignItems: 'center' }}>
            <div style={{
              width: 96, height: 96, borderRadius: 14, flexShrink: 0,
              background: row.artwork_url ? undefined : artGradient(row.title + row.artist),
              overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 10px 30px -8px ${ACCENT}50`,
            }}>
              {row.artwork_url
                ? <img src={row.artwork_url} alt={row.title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                : <span style={{ fontSize: 32, fontWeight: 800, color: '#fff' }}>{initials}</span>
              }
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: -0.5, lineHeight: 1.1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.title}</div>
              <div style={{ fontSize: 15.7, color: subFg, marginTop: 4, fontWeight: 500 }}>{row.artist}</div>
              {pills}
            </div>
          </div>
          <div style={{ padding: '0 16px 16px' }}>
            {statsRow}
            {suggestedBy}
            {previewSection}
            {voteError && <div role="alert" className="collect-error" style={{ marginTop: 12 }}>{voteError}</div>}
            {voteBtn}
          </div>
        </div>
      </div>
    );
  }

  /* ── Mobile: full-screen bottom sheet ────────────────────── */
  return (
    <div className="gst-detail-sheet">
      {/* Glow */}
      <div style={{
        position: 'absolute', top: 60, left: '50%', transform: 'translateX(-50%)',
        width: '100%', maxWidth: 420, height: 260,
        background: `radial-gradient(circle, ${ACCENT}22, transparent 65%)`,
        filter: 'blur(50px)', pointerEvents: 'none',
      }} />

      {header}

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 18px 120px', position: 'relative', zIndex: 1 }}>
        {/* Artwork */}
        <div style={{
          width: 160, height: 160, borderRadius: 22, margin: '6px auto 0',
          background: row.artwork_url ? undefined : artGradient(row.title + row.artist),
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          overflow: 'hidden',
          boxShadow: `0 20px 50px -12px ${ACCENT}70, 0 0 0 1px ${border}`,
        }}>
          {row.artwork_url
            ? <img src={row.artwork_url} alt={row.title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            : <span style={{ fontSize: 48, fontWeight: 800, color: '#fff' }}>{initials}</span>
          }
        </div>

        {/* Title + artist + pills */}
        <div style={{ marginTop: 20, textAlign: 'center' }}>
          <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: -0.7, lineHeight: 1.05 }}>{row.title}</div>
          <div style={{ fontSize: 18.2, color: subFg, marginTop: 5, fontWeight: 500 }}>{row.artist}</div>
          {pills && <div style={{ justifyContent: 'center', display: 'flex' }}>{pills}</div>}
        </div>

        {statsRow}
        {suggestedBy}
        {previewSection}
      </div>

      {/* Bottom vote CTA */}
      <div style={{
        position: 'absolute',
        bottom: 'calc(env(safe-area-inset-bottom, 0px) + 20px)',
        left: 14, right: 14, zIndex: 30,
      }}>
        {voteError && <div role="alert" className="collect-error" style={{ marginBottom: 10 }}>{voteError}</div>}
        {voteBtn}
      </div>
    </div>
  );
}
