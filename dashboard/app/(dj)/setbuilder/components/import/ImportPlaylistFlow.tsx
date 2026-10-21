'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { BuilderPlaylists } from '@/lib/api/types';
import sharedStyles from '../../setbuilder-shared.module.css';
import importStyles from '../../setbuilder-import.module.css';
import { SourceIcon, sourceColor } from '../pool/PoolBadges';
import { ModalHeader, errMessage, runImport, type ImportModalProps } from './ImportModalShared';

export default function ImportPlaylist({
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
  const [loadError, setLoadError] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const requestRef = useRef(0);
  const label = service === 'tidal' ? 'Tidal' : 'Beatport';

  const loadPlaylists = useCallback(() => {
    const requestId = ++requestRef.current;
    setPlaylists(null);
    setLoadError(false);
    api
      .getBuilderPlaylists()
      .then((result) => {
        if (requestRef.current === requestId) setPlaylists(result);
      })
      .catch(() => {
        if (requestRef.current === requestId) setLoadError(true);
      });
  }, []);

  useEffect(() => {
    loadPlaylists();
    return () => {
      requestRef.current += 1;
    };
  }, [loadPlaylists]);

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
      <div className={importStyles.imBody}>
        {playlists === null && !loadError && (
          <div className={sharedStyles.imEmpty}>Loading playlists…</div>
        )}
        {loadError && (
          <div className={sharedStyles.imEmpty} role="alert">
            <span>Could not load playlists.</span>{' '}
            <button
              type="button"
              className="btn btn-sm"
              onClick={loadPlaylists}
              aria-label="Retry playlist discovery"
            >
              Retry
            </button>
          </div>
        )}
        {playlists !== null && !connected && (
          <div className={sharedStyles.imEmpty}>
            {label} isn&apos;t connected. Link it from your account settings first.
          </div>
        )}
        {playlists !== null && connected && list.length === 0 && (
          <div className={sharedStyles.imEmpty}>No {label} playlists found.</div>
        )}
        <div className={importStyles.imList}>
          {list.map((p) => {
            const already = existingRefs.has(`${service}:${p.id}`);
            return (
              <button
                key={p.id}
                className={`${importStyles.imListItem} ${picked === p.id ? importStyles.imPicked : ''}`}
                onClick={() => setPicked(p.id)}
                disabled={busy}
              >
                <span style={{ color: sourceColor(service) }}>
                  <SourceIcon kind={service} size={16} />
                </span>
                <span className={importStyles.imListInfo}>
                  <span className={importStyles.imListTitle}>
                    {p.name}
                    {already && <span className={importStyles.imImported}> · already imported</span>}
                  </span>
                  <span className={importStyles.imListSub}>{p.num_tracks} tracks</span>
                </span>
              </button>
            );
          })}
        </div>
        <div className={importStyles.imFootnote}>
          De-duped automatically — tracks already in the pool from another source keep their
          original source tag.
        </div>
      </div>
      <div className={importStyles.imFooter}>
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
