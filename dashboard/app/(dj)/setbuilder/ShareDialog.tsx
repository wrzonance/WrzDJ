'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import type { SetSummary } from '@/lib/api-types';

interface ShareDialogProps {
  set: SetSummary;
  onClose: () => void;
  /** Called with the new token (or null after revoke) so callers can update state. */
  onChanged: (token: string | null) => void;
}

function shareUrl(token: string): string {
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  return `${origin}/shared/${token}`;
}

/** Read-only share-link management for a set: create, regenerate, revoke. */
export default function ShareDialog({ set, onClose, onChanged }: ShareDialogProps) {
  const [token, setToken] = useState<string | null>(set.share_token);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.shareSet(set.id);
      setToken(result.share_token);
      setCopied(false);
      onChanged(result.share_token);
    } catch {
      setError('Failed to update share link');
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.revokeSetShare(set.id);
      setToken(null);
      setCopied(false);
      onChanged(null);
    } catch {
      setError('Failed to revoke share link');
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(shareUrl(token));
      setCopied(true);
    } catch {
      setError('Copy failed — copy the URL manually');
    }
  };

  return (
    <div
      role="dialog"
      aria-label={`Share ${set.name}`}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ maxWidth: 480, width: '90%' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ marginBottom: '0.5rem' }}>Share &ldquo;{set.name}&rdquo;</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1rem' }}>
          Anyone with the link can view this set. They cannot edit, export, or see your account.
        </p>

        {error && (
          <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
            {error}
          </p>
        )}

        {token ? (
          <>
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
              <input
                type="text"
                className="input"
                readOnly
                value={shareUrl(token)}
                aria-label="Share URL"
                onFocus={(e) => e.target.select()}
              />
              <button type="button" className="btn btn-sm btn-primary" onClick={copy}>
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                type="button"
                className="btn btn-sm"
                style={{ background: 'var(--surface-raised)' }}
                disabled={busy}
                onClick={generate}
              >
                Regenerate
              </button>
              <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={revoke}>
                Revoke
              </button>
              <span style={{ flex: 1 }} />
              <button
                type="button"
                className="btn btn-sm"
                style={{ background: 'var(--surface-raised)' }}
                onClick={onClose}
              >
                Close
              </button>
            </div>
          </>
        ) : (
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={generate}>
              {busy ? 'Creating…' : 'Create share link'}
            </button>
            <button
              type="button"
              className="btn"
              style={{ background: 'var(--surface-raised)' }}
              onClick={onClose}
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
