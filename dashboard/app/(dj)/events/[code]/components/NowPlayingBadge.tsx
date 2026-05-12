import type { NowPlayingInfo } from '@/lib/api-types';

interface NowPlayingBadgeProps {
  nowPlaying: NowPlayingInfo | null;
}

export function NowPlayingBadge({ nowPlaying }: NowPlayingBadgeProps) {
  if (!nowPlaying) return null;

  const isLive = nowPlaying.source !== 'request' && nowPlaying.source !== 'manual';

  return (
    <div
      role="status"
      aria-label={`Now playing: ${nowPlaying.title} by ${nowPlaying.artist}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.75rem',
        background: 'var(--card)',
        borderRadius: '8px',
        padding: '0.5rem 0.75rem',
        maxWidth: '320px',
        minWidth: 0,
      }}
    >
      {nowPlaying.album_art_url ? (
        <img
          src={nowPlaying.album_art_url}
          alt="Album art"
          style={{
            width: 40,
            height: 40,
            borderRadius: 6,
            objectFit: 'cover',
            flexShrink: 0,
          }}
        />
      ) : (
        <div
          data-testid="album-art-placeholder"
          style={{
            width: 40,
            height: 40,
            borderRadius: 6,
            background: 'var(--surface-raised)',
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-tertiary)',
            fontSize: '1.25rem',
          }}
        >
          &#9835;
        </div>
      )}

      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
          {isLive && <span className="now-playing-live-badge">LIVE</span>}
          <div style={{
            fontSize: '0.875rem',
            fontWeight: 500,
            color: 'var(--text)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            {nowPlaying.title}
          </div>
        </div>
        <div style={{
          fontSize: '0.75rem',
          color: 'var(--text-secondary)',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}>
          {nowPlaying.artist}
        </div>
      </div>

      <div className="now-playing-spectrum-bars" data-testid="spectrum-bars" aria-hidden="true">
        {[...Array(5)].map((_, i) => (
          <div
            key={i}
            className="now-playing-spectrum-bar"
            style={{ animationDelay: `${i * 0.12}s` }}
          />
        ))}
      </div>
    </div>
  );
}
