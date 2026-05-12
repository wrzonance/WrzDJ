'use client';

import { ModalOverlay } from '@/components/ModalOverlay';
import { safeExternalUrl } from '@/lib/safe-url';

interface TidalLoginModalProps {
  loginUrl: string;
  userCode: string;
  polling: boolean;
  onCancel: () => void;
}

export function TidalLoginModal({
  loginUrl,
  userCode,
  polling,
  onCancel,
}: TidalLoginModalProps) {
  return (
    <ModalOverlay onClose={onCancel} card cardStyle={{ textAlign: 'center' }}>
        <h2 style={{ marginBottom: '1rem' }}>Connect Tidal</h2>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
          Visit the link below and enter the code to connect your Tidal account:
        </p>
        <a
          href={safeExternalUrl(loginUrl) ?? '#'}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'block',
            padding: '0.75rem',
            background: '#0066ff',
            color: 'white',
            borderRadius: '0.5rem',
            textDecoration: 'none',
            marginBottom: '1rem',
            fontWeight: 500,
          }}
        >
          Open Tidal Login
        </a>
        <div
          style={{
            padding: '1rem',
            background: 'var(--card)',
            borderRadius: '0.5rem',
            marginBottom: '1.5rem',
          }}
        >
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
            Your code:
          </p>
          <p style={{ fontSize: '1.5rem', fontWeight: 'bold', letterSpacing: '0.25rem' }}>
            {userCode}
          </p>
        </div>
        {polling && (
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1rem' }}>
            Waiting for authorization...
          </p>
        )}
        <button
          className="btn"
          style={{ background: 'var(--surface-raised)' }}
          onClick={onCancel}
        >
          Cancel
        </button>
    </ModalOverlay>
  );
}
