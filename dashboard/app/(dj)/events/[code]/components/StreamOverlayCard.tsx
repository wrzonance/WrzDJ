'use client';

import { useState } from 'react';
import { Tooltip } from '@/components/Tooltip';

interface StreamOverlayCardProps {
  code: string;
}

export function StreamOverlayCard({ code }: StreamOverlayCardProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const overlayUrl = `${window.location.origin}/e/${code}/overlay`;
    try {
      await navigator.clipboard.writeText(overlayUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API unavailable (non-HTTPS or permission denied)
    }
  };

  return (
    <div className="card" style={{ marginBottom: '1rem', padding: '1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <span style={{ fontWeight: 600 }}>Stream Overlay</span>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.25rem 0 0' }}>
            OBS browser source for streaming the now-playing track
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <a
            href={`/e/${code}/overlay`}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-sm"
            style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
          >
            Stream Overlay
          </a>
          <Tooltip description="Copy overlay URL for OBS browser source">
            <button
              className="btn btn-sm"
              style={{
                background: copied ? 'var(--color-success)' : 'var(--surface-raised)',
                color: copied ? 'white' : undefined,
                transition: 'background 0.2s',
              }}
              onClick={handleCopy}
            >
              {copied ? 'Copied!' : 'Copy URL'}
            </button>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
