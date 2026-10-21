'use client';

import type { CSSProperties, ReactNode } from 'react';
import type { SearchResult } from '@/lib/api';

export interface SearchResultRowAppearance {
  surface: string;
  border: string;
  secondaryText: string;
  title: { fontSize: number; letterSpacing: number };
  artist: { fontSize: number; fontWeight?: number };
  vibe: { fontSize: number };
  alignItems: CSSProperties['alignItems'];
  artworkFallback: (seed: string) => string;
}

interface SearchResultRowProps {
  result: SearchResult;
  appearance: SearchResultRowAppearance;
  onSelect: (result: SearchResult) => void;
  trailing: ReactNode;
  vibe?: {
    railColor?: string;
    label: string;
    color: string;
    className?: string;
    fontWeight?: number;
    letterSpacing?: number;
  };
  disabled?: boolean;
  className?: string;
  testId?: string;
}

export default function SearchResultRow({
  result,
  appearance,
  onSelect,
  trailing,
  vibe,
  disabled = false,
  className,
  testId,
}: SearchResultRowProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(result)}
      disabled={disabled}
      data-testid={testId}
      className={className}
      style={{
        width: '100%', textAlign: 'left', display: 'flex', alignItems: appearance.alignItems, gap: 0,
        padding: 0, borderRadius: 12, marginBottom: 6,
        background: appearance.surface, border: `1px solid ${appearance.border}`,
        color: '#fff', cursor: 'pointer', overflow: 'hidden',
      }}
    >
      {vibe?.railColor && (
        <div style={{ width: 4, flexShrink: 0, background: vibe.railColor, alignSelf: 'stretch' }} />
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 12px', flex: 1, minWidth: 0 }}>
        {result.album_art ? (
          <img
            src={result.album_art}
            alt={result.album ?? result.title}
            style={{ width: 44, height: 44, borderRadius: 8, objectFit: 'cover', flexShrink: 0 }}
          />
        ) : (
          <div style={{
            width: 44, height: 44, borderRadius: 8, flexShrink: 0,
            background: appearance.artworkFallback(result.title + result.artist),
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 13.3, fontWeight: 800, color: '#fff',
          }}>
            {`${result.title[0] ?? '?'}${result.artist[0] ?? ''}`.toUpperCase()}
          </div>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: appearance.title.fontSize, fontWeight: 700, letterSpacing: appearance.title.letterSpacing, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {result.title}
          </div>
          <div style={{ fontSize: appearance.artist.fontSize, fontWeight: appearance.artist.fontWeight, color: appearance.secondaryText, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {result.artist}
          </div>
          {vibe && (
            <div className={vibe.className} style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: appearance.vibe.fontSize, color: vibe.color, letterSpacing: vibe.letterSpacing ?? 1.2, marginTop: 4, fontWeight: vibe.fontWeight ?? 700 }}>
              {vibe.label}
            </div>
          )}
        </div>
        {trailing}
      </div>
    </button>
  );
}
