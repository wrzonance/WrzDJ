'use client';

import Link from 'next/link';
import { QRCodeSVG } from 'qrcode.react';
import type { ArchivedEvent, Event, NowPlayingInfo } from '@/lib/api';
import { NowPlayingBadge } from './requests/NowPlayingBadge';

interface ExpiryActions {
  editing: boolean;
  value: string;
  updating: boolean;
  exporting: boolean;
  onValueChange: (value: string) => void;
  onEdit: () => void;
  onSave: () => void;
  onCancel: () => void;
  onExport: () => void;
  onDelete: () => void;
}

interface EventHeaderProps {
  event: Event | ArchivedEvent;
  status: 'active' | 'expired' | 'archived';
  nowPlaying: NowPlayingInfo | null;
  joinUrl: string;
  expiry: ExpiryActions;
}

export function EventHeader({ event, status, nowPlaying, joinUrl, expiry }: EventHeaderProps) {
  const isExpiredOrArchived = status === 'expired' || status === 'archived';

  return (
    <div className="header">
      <div>
        <Link href="/dashboard" style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
          &larr; Back to Dashboard
        </Link>
        <h1 style={{ marginTop: '0.5rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%' }}>{event.name}</h1>
        <div style={{ marginTop: '0.5rem', fontSize: '0.875rem' }}>
          {isExpiredOrArchived ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <span
                className="badge"
                style={{
                  background: status === 'archived' ? 'var(--text-tertiary)' : 'var(--color-danger)',
                  color: status === 'archived'
                    ? 'var(--text-on-status-archived)'
                    : 'var(--text-on-status-danger)',
                  padding: '0.25rem 0.5rem',
                  borderRadius: '0.25rem',
                  textTransform: 'uppercase',
                  fontSize: '0.75rem',
                }}
              >
                {status}
              </span>
              <span style={{ color: 'var(--text-secondary)' }}>
                {new Date(event.expires_at).toLocaleString()}
              </span>
              <button
                className="btn btn-sm"
                style={{ background: 'var(--color-primary)', color: 'var(--text-on-primary)' }}
                onClick={expiry.onExport}
                disabled={expiry.exporting}
              >
                {expiry.exporting ? 'Exporting...' : 'Export CSV'}
              </button>
              <button className="btn btn-danger btn-sm" onClick={expiry.onDelete}>
                Delete
              </button>
            </div>
          ) : expiry.editing ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Expires:</span>
              <input
                type="datetime-local"
                className="input"
                style={{ width: 'auto', padding: '0.25rem 0.5rem', fontSize: '0.875rem' }}
                value={expiry.value}
                onChange={(event) => expiry.onValueChange(event.target.value)}
              />
              <button
                className="btn btn-primary btn-sm"
                onClick={expiry.onSave}
                disabled={expiry.updating}
              >
                {expiry.updating ? 'Saving...' : 'Save'}
              </button>
              <button
                className="btn btn-sm"
                style={{ background: 'var(--surface-raised)' }}
                onClick={expiry.onCancel}
              >
                Cancel
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ color: 'var(--text-secondary)' }}>
                Expires: {new Date(event.expires_at).toLocaleString()}
              </span>
              <button
                className="btn btn-sm"
                style={{ background: 'var(--surface-raised)' }}
                onClick={expiry.onEdit}
              >
                Edit
              </button>
              <button className="btn btn-danger btn-sm" onClick={expiry.onDelete}>
                Delete
              </button>
            </div>
          )}
        </div>
      </div>
      {!isExpiredOrArchived && nowPlaying && <NowPlayingBadge nowPlaying={nowPlaying} />}
      <div style={{ textAlign: 'center' }}>
        <div className="code" style={{ fontSize: '2rem', color: isExpiredOrArchived ? 'var(--text-tertiary)' : 'var(--color-primary)' }}>
          {event.join_code}
        </div>
        {!isExpiredOrArchived && (
          <>
            <div className="qr-container">
              <QRCodeSVG value={joinUrl} size={100} />
            </div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '0.5rem' }}>
              Scan to join
            </p>
          </>
        )}
      </div>
    </div>
  );
}
