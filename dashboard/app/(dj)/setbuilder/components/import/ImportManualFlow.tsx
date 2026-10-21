'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { SearchResult } from '@/lib/api/types';
import sharedStyles from '../../setbuilder-shared.module.css';
import importStyles from '../../setbuilder-import.module.css';
import { SourceIcon, sourceColor } from '../pool/PoolBadges';
import { ModalHeader, errMessage, runImport, type ImportModalProps } from './ImportModalShared';

export default function ImportManual({ setId, onClose, onImported, onError, commit }: ImportModalProps) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      return;
    }
    const handle = setTimeout(() => {
      setSearching(true);
      api
        .search(term)
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, 350);
    return () => clearTimeout(handle);
  }, [q]);

  const pick = async (r: SearchResult) => {
    setBusy(true);
    try {
      const service =
        r.source === 'spotify' || r.source === 'beatport' || r.source === 'tidal'
          ? r.source
          : 'manual';
      onImported(
        await runImport(commit, `Add ${r.title}`, () =>
          api.importPoolManual(setId, {
            title: r.title,
            artist: r.artist,
            album: r.album ?? null,
            genre: r.genre ?? null,
            bpm: r.bpm ?? null,
            key: r.key ?? null,
            isrc: r.isrc ?? null,
            artwork_url: r.album_art?.startsWith('https://') ? r.album_art : null,
            source_service: service,
            source_track_id: service === 'spotify' ? (r.spotify_id ?? null) : null,
          }),
        ),
      );
    } catch (e) {
      onError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <ModalHeader
        kind="manual"
        title="Add a single track"
        subtitle="Search across your connected services."
        onClose={onClose}
      />
      <div className={importStyles.imBody}>
        <input
          className={sharedStyles.imInput}
          placeholder="Search title or artist…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus
          style={{ marginBottom: 10, width: '100%' }}
        />
        <div className={importStyles.imList}>
          {results.map((r, i) => (
            <button
              key={`${r.source}-${r.spotify_id ?? r.url ?? i}`}
              className={importStyles.imListItem}
              onClick={() => pick(r)}
              disabled={busy}
            >
              <span style={{ color: sourceColor('manual') }}>
                <SourceIcon kind="manual" size={16} />
              </span>
              <span className={importStyles.imListInfo}>
                <span className={importStyles.imListTitle}>{r.title}</span>
                <span className={importStyles.imListSub}>
                  {r.artist}
                  {r.bpm ? ` · ${r.bpm} BPM` : ''}
                  {r.key ? ` · ${r.key}` : ''} · {r.source}
                </span>
              </span>
            </button>
          ))}
          {q.trim().length < 2 && (
            <div className={sharedStyles.imEmpty}>Type to search Spotify, Beatport, Tidal…</div>
          )}
          {q.trim().length >= 2 && !searching && results.length === 0 && (
            <div className={sharedStyles.imEmpty}>No matches.</div>
          )}
        </div>
      </div>
      <div className={importStyles.imFooter}>
        <button className="btn btn-sm" onClick={onClose}>
          Done
        </button>
      </div>
    </>
  );
}
