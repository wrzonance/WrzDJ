'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';

export default function PasswordChangeSection() {
  const router = useRouter();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const redirectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (redirectTimerRef.current !== null) clearTimeout(redirectTimerRef.current);
  }, []);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match');
      return;
    }
    setLoading(true);
    try {
      await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_new_password: confirmPassword,
      });
      setSuccess(true);
      redirectTimerRef.current = setTimeout(() => router.push('/login'), 1500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Password change failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section style={{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem', marginBottom: '1.5rem' }}>
      <h2 style={{ marginTop: 0, marginBottom: '1.25rem', fontSize: '1.1rem' }}>Change Password</h2>
      {success ? (
        <p style={{ color: 'var(--color-success)', margin: 0 }}>Password updated. Redirecting to login…</p>
      ) : (
        <form onSubmit={handleSubmit}>
          <label htmlFor="current-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            Current Password
          </label>
          <input
            id="current-password"
            type="password"
            value={currentPassword}
            onChange={event => setCurrentPassword(event.target.value)}
            className="input"
            style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
          />
          <label htmlFor="new-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            New Password
          </label>
          <input
            id="new-password"
            type="password"
            value={newPassword}
            onChange={event => setNewPassword(event.target.value)}
            minLength={8}
            className="input"
            style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
          />
          <label htmlFor="confirm-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            Confirm New Password
          </label>
          <input
            id="confirm-password"
            type="password"
            value={confirmPassword}
            onChange={event => setConfirmPassword(event.target.value)}
            className="input"
            style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
          />
          {error && (
            <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
              {error}
            </p>
          )}
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Updating…' : 'Update Password'}
          </button>
        </form>
      )}
    </section>
  );
}
