'use client';

import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { KioskInfo } from '@/lib/api-types';

interface PairedKiosksCardProps {
  eventCode: string;
}

export function PairedKiosksCard({ eventCode }: PairedKiosksCardProps) {
  const [kiosks, setKiosks] = useState<KioskInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');

  const fetchKiosks = useCallback(async () => {
    try {
      const all = await api.getMyKiosks();
      setKiosks(all.filter(k => k.event_code === eventCode));
    } catch {
      // Silently fail — non-critical
    } finally {
      setLoading(false);
    }
  }, [eventCode]);

  useEffect(() => {
    fetchKiosks();
  }, [fetchKiosks]);

  const handleUnpair = useCallback(async (kioskId: number) => {
    if (!confirm('Unpair this kiosk? It will need to be re-paired.')) return;
    try {
      await api.deleteKiosk(kioskId);
      setKiosks(prev => prev.filter(k => k.id !== kioskId));
    } catch {
      // Silently fail
    }
  }, []);

  const handleStartRename = useCallback((kiosk: KioskInfo) => {
    setEditingId(kiosk.id);
    setEditName(kiosk.name || '');
  }, []);

  const handleSubmitRename = useCallback(async (kioskId: number) => {
    const trimmed = editName.trim();
    try {
      const updated = await api.renameKiosk(kioskId, trimmed || null);
      setKiosks(prev => prev.map(k => k.id === kioskId ? { ...k, name: updated.name } : k));
    } catch {
      // Silently fail
    }
    setEditingId(null);
  }, [editName]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent, kioskId: number) => {
    if (e.key === 'Enter') {
      handleSubmitRename(kioskId);
    } else if (e.key === 'Escape') {
      setEditingId(null);
    }
  }, [handleSubmitRename]);

  const formatLastSeen = (iso: string | null): string => {
    if (!iso) return 'Never';
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'Just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  };

  return (
    <div className="card" style={{ marginBottom: '1rem', padding: '1rem' }}>
      <div style={{ marginBottom: '1rem' }}>
        <span style={{ fontWeight: 600 }}>Paired Kiosks</span>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.25rem 0 0' }}>
          Kiosk displays linked to this event
        </p>
      </div>

      {loading ? (
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>Loading...</p>
      ) : kiosks.length === 0 ? (
        <div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
            No kiosks paired to this event.
          </p>
          <div style={{
            background: 'var(--surface-raised)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            padding: '0.75rem 1rem',
            fontSize: '0.813rem',
            color: 'var(--text-secondary)',
          }}>
            <strong style={{ color: 'var(--text)' }}>How to pair a kiosk:</strong> Open{' '}
            <code style={{ background: 'var(--border-subtle)', padding: '0.15rem 0.4rem', borderRadius: '4px' }}>
              /kiosk-pair
            </code>{' '}
            on the kiosk device, then scan the QR code with your phone to link it to this event.
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {kiosks.map((kiosk) => (
            <div
              key={kiosk.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: 'var(--surface-raised)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                padding: '0.75rem 1rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1 }}>
                <span
                  style={{
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    background: kiosk.status === 'active' ? 'var(--color-success)' : 'var(--text-tertiary)',
                    flexShrink: 0,
                  }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  {editingId === kiosk.id ? (
                    <input
                      type="text"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onKeyDown={(e) => handleKeyDown(e, kiosk.id)}
                      onBlur={() => handleSubmitRename(kiosk.id)}
                      autoFocus
                      style={{
                        background: 'var(--card)',
                        border: '1px solid var(--border)',
                        borderRadius: '4px',
                        color: 'var(--text)',
                        padding: '0.2rem 0.4rem',
                        fontSize: '0.875rem',
                        width: '100%',
                      }}
                    />
                  ) : (
                    <>
                      <span style={{ fontWeight: 500, fontSize: '0.875rem' }}>
                        {kiosk.name || 'Unnamed Kiosk'}
                      </span>
                      <span style={{
                        display: 'block',
                        fontSize: '0.75rem',
                        color: 'var(--text-tertiary)',
                      }}>
                        Last seen: {formatLastSeen(kiosk.last_seen_at)}
                      </span>
                    </>
                  )}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', flexShrink: 0 }}>
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--surface-raised)', fontSize: '0.75rem' }}
                  onClick={() => handleStartRename(kiosk)}
                  aria-label="Rename"
                >
                  Rename
                </button>
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--color-danger-subtle)', fontSize: '0.75rem' }}
                  onClick={() => handleUnpair(kiosk.id)}
                  aria-label="Unpair"
                >
                  Unpair
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
