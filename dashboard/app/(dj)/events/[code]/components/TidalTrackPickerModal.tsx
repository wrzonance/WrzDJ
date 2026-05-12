'use client';

import { TidalSearchResult } from '@/lib/api';

interface TidalTrackPickerModalProps {
  requestId: number;
  searchQuery: string;
  searchResults: TidalSearchResult[];
  searching: boolean;
  linking: boolean;
  onSearchQueryChange: (query: string) => void;
  onSearch: () => void;
  onSelectTrack: (requestId: number, trackId: string) => void;
  onCancel: () => void;
}

export function TidalTrackPickerModal({
  requestId,
  searchQuery,
  searchResults,
  searching,
  linking,
  onSearchQueryChange,
  onSearch,
  onSelectTrack,
  onCancel,
}: TidalTrackPickerModalProps) {
  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0,0,0,0.8)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={() => !linking && onCancel()}
    >
      <div
        className="card"
        style={{
          maxWidth: '500px',
          maxHeight: '80vh',
          margin: '1rem',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ marginBottom: '1rem' }}>Link Tidal Track</h2>
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
          <input
            type="text"
            className="input"
            placeholder="Search Tidal..."
            value={searchQuery}
            onChange={(e) => onSearchQueryChange(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSearch()}
            style={{ flex: 1 }}
          />
          <button
            className="btn btn-primary"
            onClick={onSearch}
            disabled={searching}
          >
            {searching ? '...' : 'Search'}
          </button>
        </div>
        <div style={{ overflowY: 'auto', flex: 1 }}>
          {searchResults.length === 0 ? (
            <p style={{ color: 'var(--text-secondary)', textAlign: 'center' }}>
              {searching ? 'Searching...' : 'Search for a track to link'}
            </p>
          ) : (
            searchResults.map((track) => (
              <div
                key={track.track_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.75rem',
                  padding: '0.75rem',
                  borderBottom: '1px solid var(--border)',
                  cursor: 'pointer',
                }}
                onClick={() => onSelectTrack(requestId, track.track_id)}
              >
                {track.cover_url ? (
                  <img
                    src={track.cover_url}
                    alt={track.title}
                    style={{ width: '48px', height: '48px', borderRadius: '4px' }}
                  />
                ) : (
                  <div
                    style={{
                      width: '48px',
                      height: '48px',
                      borderRadius: '4px',
                      background: 'var(--surface-raised)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    <span style={{ fontSize: '1.5rem' }}>T</span>
                  </div>
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500 }}>{track.title}</div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>{track.artist}</div>
                  {track.album && (
                    <div style={{ color: 'var(--text-tertiary)', fontSize: '0.75rem' }}>{track.album}</div>
                  )}
                </div>
                {linking && (
                  <span style={{ color: 'var(--text-secondary)' }}>...</span>
                )}
              </div>
            ))
          )}
        </div>
        <div style={{ marginTop: '1rem' }}>
          <button
            className="btn"
            style={{ background: 'var(--surface-raised)', width: '100%' }}
            onClick={onCancel}
            disabled={linking}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
