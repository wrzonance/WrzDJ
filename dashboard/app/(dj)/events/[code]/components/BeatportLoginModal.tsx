'use client';

import { useState } from 'react';

import { ModalOverlay } from '@/components/ModalOverlay';

interface BeatportLoginModalProps {
  onSubmit: (username: string, password: string) => Promise<void>;
  onCancel: () => void;
}

export function BeatportLoginModal({ onSubmit, onCancel }: BeatportLoginModalProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
      setSubmitting(false);
    }
  };

  return (
    <ModalOverlay onClose={submitting ? undefined : onCancel} card cardStyle={{ width: '100%' }}>
        <h2 style={{ marginBottom: '0.5rem' }}>Connect Beatport</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1.5rem' }}>
          Enter your Beatport account credentials to link your account.
        </p>

        {error && (
          <div
            style={{
              background: 'var(--color-danger-subtle)',
              color: 'var(--color-danger)',
              padding: '0.5rem 0.75rem',
              borderRadius: '0.375rem',
              marginBottom: '1rem',
              fontSize: '0.875rem',
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '1rem' }}>
            <label
              htmlFor="bp-username"
              style={{ display: 'block', fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}
            >
              Username or Email
            </label>
            <input
              id="bp-username"
              type="text"
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              disabled={submitting}
            />
          </div>
          <div style={{ marginBottom: '1.5rem' }}>
            <label
              htmlFor="bp-password"
              style={{ display: 'block', fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}
            >
              Password
            </label>
            <input
              id="bp-password"
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              disabled={submitting}
            />
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              type="submit"
              className="btn btn-primary"
              style={{ flex: 1, background: '#01ff28', color: '#000', fontWeight: 600 }}
              disabled={submitting || !username.trim() || !password.trim()}
            >
              {submitting ? 'Connecting...' : 'Connect'}
            </button>
            <button
              type="button"
              className="btn"
              style={{ background: 'var(--surface-raised)' }}
              onClick={onCancel}
              disabled={submitting}
            >
              Cancel
            </button>
          </div>
        </form>
    </ModalOverlay>
  );
}
