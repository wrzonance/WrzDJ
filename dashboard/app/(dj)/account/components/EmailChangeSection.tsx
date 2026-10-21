'use client';

import { useState } from 'react';
import { api } from '@/lib/api';

interface EmailChangeSectionProps {
  pendingEmail: string | null;
  onPendingEmailChange: (email: string) => void;
}

export default function EmailChangeSection({
  pendingEmail,
  onPendingEmailChange,
}: EmailChangeSectionProps) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setLoading(true);
    try {
      await api.requestEmailChange({
        current_password: currentPassword,
        new_email: newEmail,
      });
      onPendingEmailChange(newEmail);
      setCurrentPassword('');
      setNewEmail('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section style={{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem' }}>
      <h2 style={{ marginTop: 0, marginBottom: '1.25rem', fontSize: '1.1rem' }}>Change Email</h2>
      {pendingEmail ? (
        <div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
            Confirmation sent to:
          </p>
          <p style={{ color: 'var(--text)', fontWeight: 500, marginBottom: '1rem' }}>{pendingEmail}</p>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', margin: 0 }}>
            Check your inbox and click the confirmation link. The link expires in 24 hours.
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit}>
          <label htmlFor="email-current-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            Password
          </label>
          <input
            id="email-current-password"
            type="password"
            value={currentPassword}
            onChange={event => setCurrentPassword(event.target.value)}
            className="input"
            style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
          />
          <label htmlFor="new-email" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            New Email Address
          </label>
          <input
            id="new-email"
            type="email"
            value={newEmail}
            onChange={event => setNewEmail(event.target.value)}
            className="input"
            style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
          />
          {error && (
            <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
              {error}
            </p>
          )}
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Sending…' : 'Send Confirmation'}
          </button>
        </form>
      )}
    </section>
  );
}
