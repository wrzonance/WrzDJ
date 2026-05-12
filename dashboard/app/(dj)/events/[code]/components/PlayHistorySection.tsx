'use client';

import { useState } from 'react';

import { PlayHistoryItem } from '@/lib/api';

const MusicIcon = () => (
  <svg
    width="18"
    height="18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
  >
    <path d="M20 4v8.5a3.5 3.5 0 1 1-2-3.163V6l-9 1.5v9a3.5 3.5 0 1 1-2-3.163V5l13-1Z" />
  </svg>
);

interface PlayHistorySectionProps {
  items: PlayHistoryItem[];
  total: number;
  exporting: boolean;
  onExport: () => void;
}

export function PlayHistorySection({ items, total, exporting, onExport }: PlayHistorySectionProps) {
  const [open, setOpen] = useState(false);

  if (items.length === 0) return null;

  return (
    <div className="card" style={{ marginTop: '2rem' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
        }}
        onClick={() => setOpen(!open)}
      >
        <h2 style={{ margin: 0, fontSize: '1.25rem' }}>
          Play History
          <span style={{ color: 'var(--text-secondary)', fontWeight: 'normal', marginLeft: '0.5rem' }}>
            ({total} {total === 1 ? 'track' : 'tracks'})
          </span>
        </h2>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
          {open ? '\u25BC' : '\u25B6'}
        </span>
      </div>
      {open && (
        <>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '0.75rem' }}>
            <button
              className="btn btn-sm"
              style={{ background: 'var(--color-status-accepted)', padding: '0.25rem 0.75rem' }}
              onClick={onExport}
              disabled={exporting}
            >
              {exporting ? 'Exporting...' : 'Export Play History'}
            </button>
          </div>
          <div className="request-list scrollable-list" style={{ marginTop: '0.75rem' }}>
            {items.map((item) => (
              <div key={item.id} className="request-item" style={{ padding: '0.5rem 0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
                  {item.album_art_url ? (
                    <img
                      src={item.album_art_url}
                      alt={item.title}
                      style={{
                        width: '36px',
                        height: '36px',
                        borderRadius: '4px',
                        objectFit: 'cover',
                      }}
                    />
                  ) : (
                    <div
                      style={{
                        width: '36px',
                        height: '36px',
                        borderRadius: '4px',
                        background: 'var(--surface-raised)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      <MusicIcon />
                    </div>
                  )}
                  <div className="request-info" style={{ flex: 1 }}>
                    <h3 style={{ margin: 0, fontSize: '0.875rem' }}>{item.title}</h3>
                    <p style={{ margin: '0.125rem 0 0', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                      {item.artist}
                    </p>
                    <p style={{ margin: '0.125rem 0 0', fontSize: '0.7rem', color: 'var(--text-tertiary)' }}>
                      {new Date(item.started_at).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span
                    className="badge"
                    style={{
                      background: item.source !== 'manual' ? 'var(--color-status-accepted)' : 'var(--color-primary)',
                      color: '#fff',
                      padding: '0.125rem 0.375rem',
                      borderRadius: '0.25rem',
                      fontSize: '0.65rem',
                    }}
                  >
                    {item.source !== 'manual' ? 'Live' : 'Manual'}
                  </span>
                  {item.matched_request_id && (
                    <span
                      className="badge"
                      style={{
                        background: 'var(--color-success)',
                        color: '#fff',
                        padding: '0.125rem 0.375rem',
                        borderRadius: '0.25rem',
                        fontSize: '0.65rem',
                      }}
                    >
                      Requested
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
