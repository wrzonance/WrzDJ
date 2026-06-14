'use client';

/**
 * Pool import modal (issue #388) — five flows:
 * event picker / Tidal playlist / Beatport playlist / public URL / manual search.
 */

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type {
  BuilderPlaylists,
  Event,
  PoolImportResult,
  PoolUrlPreview,
  SearchResult,
} from '@/lib/api-types';
import styles from '../setbuilder.module.css';
import { SourceIcon, sourceColor } from './PoolBadges';
import type { BuilderCommit } from './useSetDocumentHistory';

export type ImportKind = 'event' | 'tidal' | 'beatport' | 'public_url' | 'manual';

interface ImportModalProps {
  kind: ImportKind;
  setId: number;
  /** `${kind}:${external_ref}` keys already in the sources accordion */
  existingRefs: Set<string>;
  onClose: () => void;
  onImported: (result: PoolImportResult) => void;
  onError: (message: string) => void;
  commit?: BuilderCommit;
}

export default function ImportModal(props: ImportModalProps) {
  return (
    <div className={styles.modalWrap} role="dialog" aria-modal="true">
      <div className={styles.modalBackdrop} onClick={props.onClose} />
      <div className={styles.importModal}>
        {props.kind === 'event' && <ImportEvent {...props} />}
        {(props.kind === 'tidal' || props.kind === 'beatport') && <ImportPlaylist {...props} />}
        {props.kind === 'public_url' && <ImportPublicUrl {...props} />}
        {props.kind === 'manual' && <ImportManual {...props} />}
      </div>
    </div>
  );
}

function ModalHeader({
  kind,
  title,
  subtitle,
  onClose,
}: {
  kind: string;
  title: string;
  subtitle: string;
  onClose: () => void;
}) {
  return (
    <div className={styles.imHeader}>
      <span className={styles.imHeaderIcon} style={{ color: sourceColor(kind) }}>
        <SourceIcon kind={kind} size={20} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className={styles.imTitle}>{title}</div>
        <div className={styles.imSubtitle}>{subtitle}</div>
      </div>
      <button className={styles.iconBtn} onClick={onClose} aria-label="Close">
        ✕
      </button>
    </div>
  );
}

function errMessage(e: unknown): string {
  if (e instanceof Error && e.message) return e.message;
  return 'Import failed — try again';
}

function runImport(
  commit: BuilderCommit | undefined,
  label: string,
  action: () => Promise<PoolImportResult>,
) {
  return commit ? commit(label, action) : action();
}

function ImportEvent({ setId, existingRefs, onClose, onImported, onError, commit }: ImportModalProps) {
  const [events, setEvents] = useState<Event[] | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .getEvents()
      .then(setEvents)
      .catch(() => setEvents([]));
  }, []);

  const doImport = async () => {
    if (picked == null) return;
    setBusy(true);
    try {
      onImported(await runImport(commit, 'Import event requests', () => api.importPoolEvent(setId, picked)));
    } catch (e) {
      onError(errMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <ModalHeader
        kind="event"
        title="Import event requests"
        subtitle="Tracks that guests requested via WrzDJ."
        onClose={onClose}
      />
      <div className={styles.imBody}>
        {events === null && <div className={styles.imEmpty}>Loading events…</div>}
        {events !== null && events.length === 0 && (
          <div className={styles.imEmpty}>No events yet.</div>
        )}
        <div className={styles.imList}>
          {(events ?? []).map((e) => {
            const already = existingRefs.has(`event:${e.id}`);
            return (
              <button
                key={e.id}
                className={`${styles.imListItem} ${picked === e.id ? styles.imPicked : ''}`}
                onClick={() => setPicked(e.id)}
                disabled={busy}
              >
                <span style={{ color: sourceColor('event') }}>
                  <SourceIcon kind="event" size={16} />
                </span>
                <span className={styles.imListInfo}>
                  <span className={styles.imListTitle}>
                    {e.name}
                    {already && <span className={styles.imImported}> · already imported</span>}
                  </span>
                  <span className={styles.imListSub}>{e.code}</span>
                </span>
              </button>
            );
          })}
        </div>
        <div className={styles.imFootnote}>
          Imported tracks are de-duped automatically — tracks already in the pool keep their
          original source tag. Re-importing refreshes new requests only.
        </div>
      </div>
      <div className={styles.imFooter}>
        <button className="btn btn-sm" onClick={onClose}>
          Cancel
        </button>
        <span style={{ flex: 1 }} />
        <button
          className="btn btn-primary btn-sm"
          disabled={picked == null || busy}
          onClick={doImport}
        >
          {busy ? 'Importing…' : 'Import requests'}
        </button>
      </div>
    </>
  );
}

function ImportPlaylist({
  kind,
  setId,
  existingRefs,
  onClose,
  onImported,
  onError,
  commit,
}: ImportModalProps) {
  const service = kind as 'tidal' | 'beatport';
  const [playlists, setPlaylists] = useState<BuilderPlaylists | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const label = service === 'tidal' ? 'Tidal' : 'Beatport';

  useEffect(() => {
    api
      .getBuilderPlaylists()
      .then(setPlaylists)
      .catch(() => setPlaylists(null));
  }, []);

  const connected = playlists
    ? service === 'tidal'
      ? playlists.tidal_connected
      : playlists.beatport_connected
    : true;
  const list = playlists ? (service === 'tidal' ? playlists.tidal : playlists.beatport) : [];

  const doImport = async () => {
    if (!picked) return;
    const name = list.find((p) => p.id === picked)?.name;
    setBusy(true);
    try {
      const call = service === 'tidal' ? api.importPoolTidal : api.importPoolBeatport;
      onImported(
        await runImport(commit, `Import ${label} playlist`, () => call.call(api, setId, picked, name)),
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
        kind={service}
        title={`Import ${label} playlist`}
        subtitle={`Pulled live via your connected ${label} account.`}
        onClose={onClose}
      />
      <div className={styles.imBody}>
        {playlists === null && <div className={styles.imEmpty}>Loading playlists…</div>}
        {playlists !== null && !connected && (
          <div className={styles.imEmpty}>
            {label} isn&apos;t connected. Link it from your account settings first.
          </div>
        )}
        <div className={styles.imList}>
          {list.map((p) => {
            const already = existingRefs.has(`${service}:${p.id}`);
            return (
              <button
                key={p.id}
                className={`${styles.imListItem} ${picked === p.id ? styles.imPicked : ''}`}
                onClick={() => setPicked(p.id)}
                disabled={busy}
              >
                <span style={{ color: sourceColor(service) }}>
                  <SourceIcon kind={service} size={16} />
                </span>
                <span className={styles.imListInfo}>
                  <span className={styles.imListTitle}>
                    {p.name}
                    {already && <span className={styles.imImported}> · already imported</span>}
                  </span>
                  <span className={styles.imListSub}>{p.num_tracks} tracks</span>
                </span>
              </button>
            );
          })}
        </div>
        <div className={styles.imFootnote}>
          De-duped automatically — tracks already in the pool from another source keep their
          original source tag.
        </div>
      </div>
      <div className={styles.imFooter}>
        <button className="btn btn-sm" onClick={onClose}>
          Cancel
        </button>
        <span style={{ flex: 1 }} />
        <button className="btn btn-primary btn-sm" disabled={!picked || busy} onClick={doImport}>
          {busy ? 'Importing…' : 'Import playlist'}
        </button>
      </div>
    </>
  );
}

function ImportPublicUrl({ setId, onClose, onImported, onError, commit }: ImportModalProps) {
  const [url, setUrl] = useState('');
  const [preview, setPreview] = useState<PoolUrlPreview | null>(null);
  const [validating, setValidating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const validate = async () => {
    setValidating(true);
    setValidationError(null);
    setPreview(null);
    try {
      setPreview(await api.previewPoolUrl(setId, url.trim()));
    } catch (e) {
      setValidationError(errMessage(e));
    } finally {
      setValidating(false);
    }
  };

  const doImport = async () => {
    setBusy(true);
    try {
      onImported(
        await runImport(commit, 'Import public playlist', () => api.importPoolUrl(setId, url.trim())),
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
        kind="public_url"
        title="Import public playlist"
        subtitle="Paste a public playlist URL from Spotify or Tidal."
        onClose={onClose}
      />
      <div className={styles.imBody}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <input
            className={styles.imInput}
            placeholder="https://open.spotify.com/playlist/…"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
              setPreview(null);
              setValidationError(null);
            }}
            autoFocus
          />
          <button
            className="btn btn-primary btn-sm"
            disabled={!/^https:\/\/.+/.test(url.trim()) || validating}
            onClick={validate}
          >
            {validating ? 'Checking…' : 'Validate'}
          </button>
        </div>

        {validationError && <div className={styles.imError}>{validationError}</div>}

        {preview && !preview.supported && (
          <div className={styles.imError}>{preview.message ?? 'Provider not supported yet.'}</div>
        )}

        {preview && preview.supported && (
          <div className={styles.imPreviewCard}>
            <div className={styles.imPreviewRow}>
              <span className={styles.imPreviewLabel}>Detected</span>
              <span>{preview.provider === 'spotify' ? 'Spotify' : 'Tidal'} · public playlist</span>
            </div>
            <div className={styles.imPreviewRow}>
              <span className={styles.imPreviewLabel}>Name</span>
              <span>{preview.name ?? '—'}</span>
            </div>
            <div className={styles.imPreviewRow}>
              <span className={styles.imPreviewLabel}>Tracks</span>
              <span>{preview.track_count ?? '—'} found · de-duped on import</span>
            </div>
            {preview.owner && (
              <div className={styles.imPreviewRow}>
                <span className={styles.imPreviewLabel}>Owner</span>
                <span>{preview.owner}</span>
              </div>
            )}
          </div>
        )}

        <div className={styles.imFootnote}>
          We never fetch the URL itself — the playlist ID is extracted and pulled via the official
          API. Apple Music / YouTube / SoundCloud support is planned.
        </div>
      </div>
      <div className={styles.imFooter}>
        <button className="btn btn-sm" onClick={onClose}>
          Cancel
        </button>
        <span style={{ flex: 1 }} />
        <button
          className="btn btn-primary btn-sm"
          disabled={!preview?.supported || busy}
          onClick={doImport}
        >
          {busy ? 'Importing…' : 'Import playlist'}
        </button>
      </div>
    </>
  );
}

function ImportManual({ setId, onClose, onImported, onError, commit }: ImportModalProps) {
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
      <div className={styles.imBody}>
        <input
          className={styles.imInput}
          placeholder="Search title or artist…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus
          style={{ marginBottom: 10, width: '100%' }}
        />
        <div className={styles.imList}>
          {results.map((r, i) => (
            <button
              key={`${r.source}-${r.spotify_id ?? r.url ?? i}`}
              className={styles.imListItem}
              onClick={() => pick(r)}
              disabled={busy}
            >
              <span style={{ color: sourceColor('manual') }}>
                <SourceIcon kind="manual" size={16} />
              </span>
              <span className={styles.imListInfo}>
                <span className={styles.imListTitle}>{r.title}</span>
                <span className={styles.imListSub}>
                  {r.artist}
                  {r.bpm ? ` · ${r.bpm} BPM` : ''}
                  {r.key ? ` · ${r.key}` : ''} · {r.source}
                </span>
              </span>
            </button>
          ))}
          {q.trim().length < 2 && (
            <div className={styles.imEmpty}>Type to search Spotify, Beatport, Tidal…</div>
          )}
          {q.trim().length >= 2 && !searching && results.length === 0 && (
            <div className={styles.imEmpty}>No matches.</div>
          )}
        </div>
      </div>
      <div className={styles.imFooter}>
        <button className="btn btn-sm" onClick={onClose}>
          Done
        </button>
      </div>
    </>
  );
}
