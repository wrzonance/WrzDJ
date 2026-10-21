import type { CSSProperties } from 'react';
import type { Pairing, PoolTrack } from '@/lib/api/types';
import { BPM_TIER_COLORS, KEY_TIER_COLORS, bpmPercentDelta, camelotMixTier } from '../curve/curveMath';

import pairingStyles from '../../setbuilder-pairings.module.css';

function initials(track: PoolTrack | null | undefined): string {
  const artist = track?.artist || track?.title || '?';
  return artist
    .split(/[,\s]+/)
    .filter(Boolean)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

function artStyle(trackId: string | null | undefined): CSSProperties {
  const seed = [...(trackId ?? 'manual')].reduce((acc, c) => acc + c.charCodeAt(0), 0);
  const h1 = (seed * 37) % 360;
  const h2 = (h1 + 70) % 360;
  return { background: `linear-gradient(135deg, hsl(${h1} 58% 35%), hsl(${h2} 54% 24%))` };
}

export function pairingMatches(pairing: Pairing, q: string): boolean {
  if (!q) return true;
  const hay = [
    pairing.from_track?.title,
    pairing.from_track?.artist,
    pairing.into_track?.title,
    pairing.into_track?.artist,
    pairing.from_track_id,
    pairing.into_track_id,
    pairing.note,
    ...(pairing.tags ?? []),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return hay.includes(q.toLowerCase());
}

export function TrackArt({ track }: { track: PoolTrack | null | undefined }) {
  return (
    <span className={pairingStyles.pairingArt} style={artStyle(track?.track_id)}>
      {initials(track)}
    </span>
  );
}

export function LinkIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M10.5 13.5 13.5 10.5M8.5 17.5H7.8a4.8 4.8 0 0 1 0-9.6h3.4M12.8 16.1h3.4a4.8 4.8 0 1 0 0-9.6h-.7"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

export function PairingMini({ pairing }: { pairing: Pairing }) {
  return (
    <div className={pairingStyles.pairingMini}>
      <div className={pairingStyles.pairingMiniTrack}>
        <TrackArt track={pairing.from_track} />
        <span className={pairingStyles.pairingMiniInfo}>
          <span className={pairingStyles.pairingMiniTitle}>
            {pairing.from_track?.title ?? pairing.from_track_id}
          </span>
          <span className={pairingStyles.pairingMiniArtist}>{pairing.from_track?.artist ?? 'Unknown'}</span>
        </span>
      </div>
      <span className={pairingStyles.pairingArrow}>-&gt;</span>
      <div className={pairingStyles.pairingMiniTrack}>
        <TrackArt track={pairing.into_track} />
        <span className={pairingStyles.pairingMiniInfo}>
          <span className={pairingStyles.pairingMiniTitle}>
            {pairing.into_track?.title ?? pairing.into_track_id}
          </span>
          <span className={pairingStyles.pairingMiniArtist}>{pairing.into_track?.artist ?? 'Unknown'}</span>
        </span>
      </div>
    </div>
  );
}

export function CompatibilityChips({ from, into }: { from?: PoolTrack | null; into?: PoolTrack | null }) {
  const bpm = bpmPercentDelta(from?.bpm ?? null, into?.bpm ?? null);
  const key = camelotMixTier(from?.camelot ?? from?.key ?? null, into?.camelot ?? into?.key ?? null);
  const bpmColor = BPM_TIER_COLORS[bpm.tier];
  const keyColor = KEY_TIER_COLORS[key.tier];
  return (
    <>
      <span className={pairingStyles.pairingMetricChip} style={{ color: bpmColor.chip, background: bpmColor.chipBg }}>
        {bpm.pct == null ? '? BPM' : `${bpm.pct.toFixed(1)}% BPM`}
      </span>
      <span className={pairingStyles.pairingMetricChip} style={{ color: keyColor.chip, background: keyColor.chipBg }}>
        {key.label}
      </span>
    </>
  );
}
