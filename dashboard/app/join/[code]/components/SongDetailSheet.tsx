'use client';

import { GuestRequestInfo } from '@/lib/api';
import { artGradient } from '@/lib/art-gradient';
import TickNumber from './TickNumber';

interface Props {
  track: GuestRequestInfo;
  rank: number;
  totalCount: number;
  votes: number;
  voted: boolean;
  canVote: boolean;
  isVoting: boolean;
  onVote: () => void;
  onClose: () => void;
}

const ACCENT = '#00f0ff';
const ACCENT2 = '#ff2bd6';

export default function SongDetailSheet({
  track, rank, totalCount, votes, voted, canVote, isVoting, onVote, onClose,
}: Props) {
  const initials = `${track.title[0] ?? '?'}${track.artist[0] ?? ''}`.toUpperCase();
  const surface = 'rgba(255,255,255,0.05)';
  const border = 'rgba(255,255,255,0.1)';
  const subFg = 'rgba(255,255,255,0.55)';
  const subFg2 = 'rgba(255,255,255,0.35)';

  return (
    <div className="gst-detail-sheet">
      {/* Glow */}
      <div style={{
        position: 'absolute', top: 80, left: '50%', transform: 'translateX(-50%)',
        width: '100%', maxWidth: 420, height: 300,
        background: `radial-gradient(circle, ${ACCENT}28, transparent 65%)`,
        filter: 'blur(50px)', pointerEvents: 'none',
      }} />

      {/* Header */}
      <div style={{ padding: '12px 16px 6px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'relative', zIndex: 1 }}>
        <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, color: subFg, letterSpacing: 1.5 }}>
          QUEUE · #{rank}
        </div>
        <button
          onClick={onClose}
          style={{
            width: 44, height: 44, borderRadius: 13,
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

      {/* Scrollable body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 18px 140px', position: 'relative', zIndex: 1 }}>
        {/* Artwork */}
        <div style={{
          width: 160, height: 160, borderRadius: 22, margin: '6px auto 0',
          background: track.artwork_url ? undefined : artGradient(track.title + track.artist),
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          overflow: 'hidden',
          boxShadow: `0 20px 50px -12px ${ACCENT}70, 0 0 0 1px ${border}`,
        }}>
          {track.artwork_url ? (
            <img
              src={track.artwork_url}
              alt={track.title}
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />
          ) : (
            <span style={{
              fontSize: 48, fontWeight: 800, color: '#fff', letterSpacing: 1,
              textShadow: '0 4px 30px rgba(0,0,0,0.3)',
            }}>
              {initials}
            </span>
          )}
        </div>

        {/* Title + artist */}
        <div style={{ marginTop: 22, textAlign: 'center' }}>
          <div style={{ fontSize: 33.9, fontWeight: 800, letterSpacing: -0.8, lineHeight: 1.05 }}>
            {track.title}
          </div>
          <div style={{ fontSize: 20.6, color: subFg, marginTop: 5, fontWeight: 500 }}>
            {track.artist}
          </div>
          {(track.bpm || track.musical_key) && (
            <div style={{ display: 'flex', gap: 6, marginTop: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
              {track.bpm && (
                <span style={{
                  fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, fontWeight: 700,
                  padding: '3px 9px', borderRadius: 6,
                  background: `${ACCENT}18`, border: `1px solid ${ACCENT}50`, color: ACCENT,
                  letterSpacing: 1,
                }}>
                  {track.bpm} BPM
                </span>
              )}
              {track.musical_key && (
                <span style={{
                  fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, fontWeight: 700,
                  padding: '3px 9px', borderRadius: 6,
                  background: 'rgba(255,255,255,0.06)', border: `1px solid ${border}`,
                  color: 'rgba(255,255,255,0.7)', letterSpacing: 1,
                }}>
                  {track.musical_key}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Stats */}
        <div style={{ display: 'flex', gap: 8, marginTop: 18 }}>
          <div style={{ flex: 1, padding: 14, borderRadius: 14, background: surface, border: `1px solid ${border}` }}>
            <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10.3, color: subFg, letterSpacing: 1.5 }}>
              UPVOTES
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 5, marginTop: 4 }}>
              <TickNumber
                value={votes}
                style={{
                  fontFamily: 'var(--font-mono, monospace)', fontSize: 36.3, fontWeight: 800,
                  lineHeight: '1', color: ACCENT, fontVariantNumeric: 'tabular-nums',
                }}
              />
              <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 12.1, color: subFg2 }}>
                votes
              </span>
            </div>
          </div>
          <div style={{ flex: 1, padding: 14, borderRadius: 14, background: surface, border: `1px solid ${border}` }}>
            <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10.3, color: subFg, letterSpacing: 1.5 }}>
              QUEUE RANK
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 5, marginTop: 4 }}>
              <span style={{
                fontFamily: 'var(--font-mono, monospace)', fontSize: 36.3, fontWeight: 800,
                lineHeight: '1', color: '#fff', fontVariantNumeric: 'tabular-nums',
              }}>
                #{rank}
              </span>
              <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 12.1, color: subFg2 }}>
                of {totalCount}
              </span>
            </div>
          </div>
        </div>

        {/* Requested by */}
        {track.nickname && (
          <div style={{
            marginTop: 14, padding: 14, borderRadius: 14,
            background: surface, border: `1px solid ${border}`,
            display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <div style={{
              width: 46, height: 46, borderRadius: '50%', flexShrink: 0,
              background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT2})`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16.9, fontWeight: 800, color: '#000',
            }}>
              {track.nickname[0]?.toUpperCase() ?? '?'}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10.3, color: subFg, letterSpacing: 1.5 }}>
                REQUESTED BY
              </div>
              <div style={{ fontSize: 18.2, fontWeight: 700, marginTop: 2 }}>
                {track.nickname}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Bottom vote CTA */}
      <div style={{
        position: 'absolute',
        bottom: 'calc(env(safe-area-inset-bottom, 0px) + 20px)',
        left: 14, right: 14, zIndex: 30,
      }}>
        <button
          onClick={onVote}
          disabled={isVoting || !canVote}
          style={{
            width: '100%', height: 64, borderRadius: 18,
            background: voted ? 'transparent' : `linear-gradient(90deg, ${ACCENT}, ${ACCENT2})`,
            border: voted ? `1.5px solid ${ACCENT}` : 'none',
            color: voted ? ACCENT : '#000',
            fontFamily: 'var(--font-grotesk, system-ui)', fontSize: 18.2, fontWeight: 800, letterSpacing: 0.4,
            cursor: isVoting ? 'wait' : canVote ? 'pointer' : 'default',
            opacity: isVoting || !canVote ? 0.65 : 1,
            boxShadow: voted ? 'none' : `0 14px 36px -8px ${ACCENT}90, 0 0 0 1px rgba(255,255,255,0.15) inset`,
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
            transition: 'all 160ms',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M2 9L7 3L12 9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          {voted ? 'VOTED · TAP TO REMOVE' : 'UPVOTE THIS TRACK'}
        </button>
      </div>
    </div>
  );
}
