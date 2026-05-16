'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';

export default function AccountPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [passwordLoading, setPasswordLoading] = useState(false);

  const [emailCurrentPassword, setEmailCurrentPassword] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [emailError, setEmailError] = useState('');
  const [emailPending, setEmailPending] = useState<string | null>(null);
  const [emailLoading, setEmailLoading] = useState(false);

  const redirectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (redirectTimerRef.current !== null) clearTimeout(redirectTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, isLoading, router]);

  useEffect(() => {
    if (isAuthenticated) {
      let isActive = true;
      api.getMe()
        .then(user => { if (isActive) setEmailPending(prev => prev ?? (user.pending_email ?? null)); })
        .catch(() => {});
      return () => { isActive = false; };
    }
  }, [isAuthenticated]);

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError('');
    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match');
      return;
    }
    setPasswordLoading(true);
    try {
      await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_new_password: confirmPassword,
      });
      setPasswordSuccess(true);
      redirectTimerRef.current = setTimeout(() => router.push('/login'), 1500);
    } catch (err: unknown) {
      setPasswordError(err instanceof Error ? err.message : 'Password change failed');
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleEmailRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    setEmailError('');
    setEmailLoading(true);
    try {
      await api.requestEmailChange({
        current_password: emailCurrentPassword,
        new_email: newEmail,
      });
      setEmailPending(newEmail);
      setEmailCurrentPassword('');
      setNewEmail('');
    } catch (err: unknown) {
      setEmailError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setEmailLoading(false);
    }
  };

  if (isLoading || !isAuthenticated) return null;

  return (
    <main style={{ maxWidth: '480px', margin: '0 auto', padding: '2rem 1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        <Link href="/dashboard" style={{ color: 'var(--text-secondary)', textDecoration: 'none', fontSize: '0.875rem' }}>
          ← Dashboard
        </Link>
        <h1 style={{ margin: 0, fontSize: '1.5rem' }}>Account Settings</h1>
      </div>

      <div style={{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem', marginBottom: '1.5rem' }}>
        <h2 style={{ marginTop: 0, marginBottom: '1.25rem', fontSize: '1.1rem' }}>Change Password</h2>
        {passwordSuccess ? (
          <p style={{ color: 'var(--color-success)', margin: 0 }}>Password updated. Redirecting to login…</p>
        ) : (
          <form onSubmit={handlePasswordChange}>
            <label htmlFor="current-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
              Current Password
            </label>
            <input
              id="current-password"
              type="password"
              value={currentPassword}
              onChange={e => setCurrentPassword(e.target.value)}
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
              onChange={e => setNewPassword(e.target.value)}
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
              onChange={e => setConfirmPassword(e.target.value)}
              className="input"
              style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
            />
            {passwordError && (
              <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
                {passwordError}
              </p>
            )}
            <button type="submit" className="btn btn-primary" disabled={passwordLoading}>
              {passwordLoading ? 'Updating…' : 'Update Password'}
            </button>
          </form>
        )}
      </div>

      <div style={{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem' }}>
        <h2 style={{ marginTop: 0, marginBottom: '1.25rem', fontSize: '1.1rem' }}>Change Email</h2>
        {emailPending ? (
          <div>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              Confirmation sent to:
            </p>
            <p style={{ color: 'var(--text)', fontWeight: 500, marginBottom: '1rem' }}>{emailPending}</p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', margin: 0 }}>
              Check your inbox and click the confirmation link. The link expires in 24 hours.
            </p>
          </div>
        ) : (
          <form onSubmit={handleEmailRequest}>
            <label htmlFor="email-current-password" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
              Password
            </label>
            <input
              id="email-current-password"
              type="password"
              value={emailCurrentPassword}
              onChange={e => setEmailCurrentPassword(e.target.value)}
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
              onChange={e => setNewEmail(e.target.value)}
              className="input"
              style={{ width: '100%', marginBottom: '1rem', boxSizing: 'border-box' }}
            />
            {emailError && (
              <p style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
                {emailError}
              </p>
            )}
            <button type="submit" className="btn btn-primary" disabled={emailLoading}>
              {emailLoading ? 'Sending…' : 'Send Confirmation'}
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
