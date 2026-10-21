'use client';

import { useState } from 'react';
import { canEmbed, getEmbedUrl, getPreviewSource, type PreviewData } from '@/lib/preview-embed';
import { safeExternalUrl } from '@/lib/safe-url';

/**
 * Embeddable audio preview player for song cards.
 *
 * Three render paths:
 * 1. Spotify/Tidal: toggle button → collapsible iframe embed
 * 2. Beatport: small "Open in Beatport" link (no embed API)
 * 3. Everything else: renders nothing
 */
export function PreviewPlayer({ data }: { data: PreviewData }) {
  const [expanded, setExpanded] = useState(false);
  const source = getPreviewSource(data);

  // Beatport: link-button fallback (no embed support)
  if (source === 'beatport' && data.sourceUrl && /^https?:\/\//.test(data.sourceUrl)) {
    return (
      <a
        href={safeExternalUrl(data.sourceUrl) ?? '#'}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Open in Beatport (opens in new tab)"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.25rem',
          fontSize: '0.7rem',
          color: 'var(--text-secondary)',
          textDecoration: 'none',
          marginTop: '0.375rem',
        }}
      >
        Open in Beatport ↗
      </a>
    );
  }

  // Only render toggle for embeddable sources
  if (!canEmbed(data)) return null;

  const embedUrl = getEmbedUrl(data);
  if (!embedUrl) return null;

  const sourceLabel = source === 'spotify' ? 'Spotify' : 'Tidal';

  return (
    <div style={{ marginTop: '0.375rem' }}>
      <button
        onClick={() => setExpanded((prev) => !prev)}
        aria-label={`${expanded ? 'Hide' : 'Show'} ${sourceLabel} preview`}
        aria-expanded={expanded}
        style={{
          background: 'none',
          border: '1px solid #374151',
          borderRadius: '0.375rem',
          color: 'var(--text-secondary)',
          fontSize: '0.7rem',
          padding: '0.125rem 0.5rem',
          cursor: 'pointer',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.25rem',
        }}
      >
        {expanded ? '▼' : '▶'} Preview
      </button>
      {expanded && (
        <div
          style={{
            width: '100%',
            borderRadius: '0.5rem',
            overflow: 'hidden',
            marginTop: '0.5rem',
            backgroundColor: 'var(--card)',
          }}
        >
          <iframe
            src={embedUrl}
            width="100%"
            height="152"
            allow="encrypted-media"
            sandbox="allow-scripts allow-same-origin allow-popups"
            loading="lazy"
            title={`${sourceLabel} audio preview`}
            style={{
              borderRadius: '0.5rem',
              border: 'none',
              display: 'block',
            }}
          />
        </div>
      )}
    </div>
  );
}
