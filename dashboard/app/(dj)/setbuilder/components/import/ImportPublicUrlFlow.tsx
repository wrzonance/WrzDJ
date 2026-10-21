'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import type { PoolUrlPreview } from '@/lib/api/types';
import sharedStyles from '../../setbuilder-shared.module.css';
import importStyles from '../../setbuilder-import.module.css';
import { ModalHeader, errMessage, runImport, type ImportModalProps } from './ImportModalShared';

export default function ImportPublicUrl({ setId, onClose, onImported, onError, commit }: ImportModalProps) {
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
      <div className={importStyles.imBody}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <input
            className={sharedStyles.imInput}
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

        {validationError && <div className={sharedStyles.imError}>{validationError}</div>}

        {preview && !preview.supported && (
          <div className={sharedStyles.imError}>{preview.message ?? 'Provider not supported yet.'}</div>
        )}

        {preview && preview.supported && (
          <div className={importStyles.imPreviewCard}>
            <div className={importStyles.imPreviewRow}>
              <span className={importStyles.imPreviewLabel}>Detected</span>
              <span>{preview.provider === 'spotify' ? 'Spotify' : 'Tidal'} · public playlist</span>
            </div>
            <div className={importStyles.imPreviewRow}>
              <span className={importStyles.imPreviewLabel}>Name</span>
              <span>{preview.name ?? '—'}</span>
            </div>
            <div className={importStyles.imPreviewRow}>
              <span className={importStyles.imPreviewLabel}>Tracks</span>
              <span>{preview.track_count ?? '—'} found · de-duped on import</span>
            </div>
            {preview.owner && (
              <div className={importStyles.imPreviewRow}>
                <span className={importStyles.imPreviewLabel}>Owner</span>
                <span>{preview.owner}</span>
              </div>
            )}
          </div>
        )}

        <div className={importStyles.imFootnote}>
          We never fetch the URL itself — the playlist ID is extracted and pulled via the official
          API. Apple Music / YouTube / SoundCloud support is planned.
        </div>
      </div>
      <div className={importStyles.imFooter}>
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
