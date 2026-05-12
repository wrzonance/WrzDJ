'use client';

import { useState, useCallback } from 'react';
import { api } from '@/lib/api';
import type { SearchResult } from '@/lib/api-types';
import { KeyBadge, BpmBadge, GenreBadge } from '@/components/MusicBadges';
import { ModalOverlay } from '@/components/ModalOverlay';
import { PreviewPlayer } from '@/components/PreviewPlayer';

interface DjSongSearchModalProps {
  code: string;
  onSongAdded: () => void;
  onClose: () => void;
}

export function DjSongSearchModal({ code, onSongAdded, onClose }: DjSongSearchModalProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());

  const handleSearch = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    setSearching(true);
    try {
      const data = await api.eventSearch(code, trimmed);
      setResults(data);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }, [code, query]);

  const handleAddSong = useCallback(async (result: SearchResult) => {
    const trackKey = result.spotify_id || result.url || `${result.artist}-${result.title}`;
    setAdding(trackKey);
    try {
      const created = await api.submitRequest(
        code,
        result.artist,
        result.title,
        undefined,
        result.url || undefined,
        result.album_art || undefined,
        query,
        {
          source: result.source,
          genre: result.genre || undefined,
          bpm: result.bpm || undefined,
          musical_key: result.key || undefined,
        },
        result.source,
      );
      await api.updateRequestStatus(created.id, 'accepted');
      setAddedIds((prev) => new Set([...prev, trackKey]));
      onSongAdded();
    } catch {
      // Silently fail — request may already exist
    } finally {
      setAdding(null);
    }
  }, [code, query, onSongAdded]);

  return (
    <ModalOverlay
      onClose={onClose}
      card
      cardStyle={{
        maxWidth: '550px',
        width: '100%',
        maxHeight: '80vh',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
        <h2 style={{ marginBottom: '1rem' }}>Search For Song</h2>
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
          <input
            type="text"
            className="input"
            placeholder="Search for a song or artist..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            style={{ flex: 1 }}
            autoFocus
          />
          <button
            className="btn btn-primary"
            onClick={handleSearch}
            disabled={searching || !query.trim()}
          >
            {searching ? '...' : 'Search'}
          </button>
        </div>

        <div style={{ overflowY: 'auto', flex: 1 }}>
          {results.length === 0 && !searching && (
            <p style={{ color: 'var(--text-secondary)', textAlign: 'center' }}>
              Search for a song to add to your queue
            </p>
          )}
          {searching && (
            <p style={{ color: 'var(--text-secondary)', textAlign: 'center' }}>Searching...</p>
          )}
          {results.map((result) => {
            const trackKey = result.spotify_id || result.url || `${result.artist}-${result.title}`;
            const isAdding = adding === trackKey;
            const isAdded = addedIds.has(trackKey);

            return (
              <div
                key={trackKey}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.75rem',
                  padding: '0.75rem',
                  borderBottom: '1px solid var(--border)',
                  opacity: isAdded ? 0.5 : 1,
                }}
              >
                {result.album_art ? (
                  <img
                    src={result.album_art}
                    alt={result.title}
                    style={{ width: '48px', height: '48px', borderRadius: '4px', objectFit: 'cover', flexShrink: 0 }}
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
                      flexShrink: 0,
                    }}
                  >
                    <span style={{ fontSize: '1.5rem' }}>
                      {result.source === 'beatport' ? 'B' : result.source === 'tidal' ? 'T' : 'S'}
                    </span>
                  </div>
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {result.title}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {result.artist}
                  </div>
                  <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap', marginTop: '0.25rem', alignItems: 'center' }}>
                    {result.bpm && <BpmBadge bpm={result.bpm} />}
                    {result.key && <KeyBadge musicalKey={result.key} />}
                    {result.genre && <GenreBadge genre={result.genre} />}
                    <PreviewPlayer data={{ source: result.source, sourceUrl: result.url }} />
                  </div>
                </div>
                <button
                  className="btn btn-sm"
                  style={{
                    background: isAdded ? 'var(--color-success)' : 'var(--color-status-accepted)',
                    color: '#fff',
                    flexShrink: 0,
                    minWidth: '60px',
                  }}
                  onClick={() => handleAddSong(result)}
                  disabled={isAdding || isAdded}
                >
                  {isAdded ? 'Added' : isAdding ? '...' : 'Add'}
                </button>
              </div>
            );
          })}
        </div>

        <div style={{ marginTop: '1rem' }}>
          <button
            className="btn"
            style={{ background: 'var(--surface-raised)', width: '100%' }}
            onClick={onClose}
          >
            Close
          </button>
        </div>
    </ModalOverlay>
  );
}
