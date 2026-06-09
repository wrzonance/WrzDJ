'use client';

/**
 * Pool row badges + source iconography (issue #388).
 * Translated from the design prototype (pool-panel.jsx) — Camelot key,
 * BPM and energy mini-badges plus per-source-kind SVG icons and colors.
 */

import { getCamelotColor } from '@/lib/camelot-colors';

export type SourceKind = 'event' | 'tidal' | 'beatport' | 'public_url' | 'manual';

export const SOURCE_COLORS: Record<SourceKind, string> = {
  event: '#b78bff',
  tidal: '#00ffff',
  beatport: '#88e837',
  public_url: '#ff70b4',
  manual: '#9ca3af',
};

export function sourceColor(kind: string | undefined): string {
  return SOURCE_COLORS[(kind ?? 'manual') as SourceKind] ?? '#9ca3af';
}

export function SourceIcon({ kind, size = 14 }: { kind: string; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  if (kind === 'event')
    return (
      <svg {...common} aria-hidden>
        <rect x="3" y="4" width="18" height="18" rx="2" />
        <path d="M16 2v4M8 2v4M3 10h18" />
      </svg>
    );
  if (kind === 'tidal')
    return (
      <svg {...common} aria-hidden>
        <path d="m12 4 4 4-4 4-4-4 4-4Z M4 12l4 4 4-4-4-4-4 4Z M20 12l-4 4-4-4 4-4 4 4Z M12 20l-4-4 4-4 4 4-4 4Z" />
      </svg>
    );
  if (kind === 'beatport')
    return (
      <svg {...common} aria-hidden>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="4" />
      </svg>
    );
  if (kind === 'public_url')
    return (
      <svg {...common} aria-hidden>
        <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
        <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
      </svg>
    );
  // manual
  return (
    <svg {...common} aria-hidden>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function CamelotBadge({ camelot }: { camelot: string | null }) {
  if (!camelot) return null;
  const c = getCamelotColor(camelot);
  return (
    <span
      style={{
        background: c.bg,
        color: c.text,
        fontSize: 10,
        fontWeight: 700,
        padding: '1px 5px',
        borderRadius: 4,
        lineHeight: '14px',
      }}
      title={`Camelot ${camelot}`}
    >
      {camelot}
    </span>
  );
}

export function BpmBadge({ bpm }: { bpm: number | null }) {
  if (bpm == null) return null;
  return (
    <span
      style={{
        background: 'var(--surface-raised, #23262d)',
        color: 'var(--text-secondary)',
        fontSize: 10,
        fontWeight: 600,
        padding: '1px 5px',
        borderRadius: 4,
        lineHeight: '14px',
      }}
      title={`${Math.round(bpm)} BPM`}
    >
      {Math.round(bpm)}
    </span>
  );
}

export function EnergyMini({ value }: { value: number | null }) {
  const v = value ?? 0;
  return (
    <span
      style={{ display: 'inline-flex', alignItems: 'flex-end', gap: 1.5, height: 12 }}
      title={value == null ? 'Energy not analyzed yet' : `Energy ${value}/10`}
      aria-label={value == null ? 'Energy unknown' : `Energy ${value} of 10`}
    >
      {[0, 1, 2, 3, 4].map((i) => {
        const on = v / 2 > i;
        return (
          <span
            key={i}
            style={{
              width: 3,
              borderRadius: 1,
              height: on ? `${30 + i * 17}%` : '12%',
              background: on ? 'var(--color-primary, #8b5cf6)' : 'var(--border, #3a3a3a)',
            }}
          />
        );
      })}
    </span>
  );
}
