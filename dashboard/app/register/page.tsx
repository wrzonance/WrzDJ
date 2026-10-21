'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import '@/lib/turnstile';

export default function RegisterPage() {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const [registrationEnabled, setRegistrationEnabled] = useState<boolean | null>(null);
  const [siteKey, setSiteKey] = useState('');
  const [turnstileToken, setTurnstileToken] = useState('');
  const turnstileRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);

  useEffect(() => {
    api.getPublicSettings()
      .then((s) => {
        setRegistrationEnabled(s.registration_enabled);
        setSiteKey(s.turnstile_site_key);
      })
      .catch(() => setRegistrationEnabled(false));
  }, []);

  useEffect(() => {
    if (!siteKey || !turnstileRef.current) return;

    const script = document.createElement('script');
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?onload=onTurnstileLoad';
    script.async = true;

    (window as unknown as Record<string, unknown>).onTurnstileLoad = () => {
      if (turnstileRef.current && window.turnstile) {
        widgetIdRef.current = window.turnstile.render(turnstileRef.current, {
          sitekey: siteKey,
          callback: (token: string) => setTurnstileToken(token),
        });
      }
    };

    document.head.appendChild(script);
    return () => {
      script.remove();
      delete (window as unknown as Record<string, unknown>).onTurnstileLoad;
    };
  }, [siteKey]);

  if (registrationEnabled === null) {
    return (
      <div className="container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  if (!registrationEnabled) {
    return (
      <div className="container" style={{ maxWidth: '400px', marginTop: '100px' }}>
        <div className="card" style={{ textAlign: 'center' }}>
          <h1 style={{ marginBottom: '1rem' }}>Registration Disabled</h1>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
            Self-registration is currently disabled. Contact an administrator.
          </p>
          <Link href="/login">
            <button className="btn btn-primary">Back to Login</button>
          </Link>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setLoading(true);
    try {
      const result = await api.register({
        username,
        email,
        password,
        confirm_password: confirmPassword,
        turnstile_token: turnstileToken,
      });
      setSuccess(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.reset(widgetIdRef.current);
      }
      setTurnstileToken('');
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="container" style={{ maxWidth: '400px', marginTop: '100px' }}>
        <div className="card" style={{ textAlign: 'center' }}>
          <h1 style={{ marginBottom: '1rem', color: '#22c55e' }}>Registration Submitted</h1>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
            {success}
          </p>
          <Link href="/login">
            <button className="btn btn-primary">Go to Login</button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="container" style={{ maxWidth: '400px', marginTop: '60px' }}>
      <div className="card">
        <h1 style={{ marginBottom: '1.5rem', textAlign: 'center' }}>Create Account</h1>

        {error && (
          <div style={{ color: '#ef4444', marginBottom: '1rem', textAlign: 'center' }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="reg-username">Username</label>
            <input
              id="reg-username"
              type="text"
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              maxLength={50}
              pattern="^[a-zA-Z0-9_]+$"
              title="Letters, numbers, and underscores only"
            />
          </div>

          <div className="form-group">
            <label htmlFor="reg-email">Email</label>
            <input
              id="reg-email"
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="reg-password">Password</label>
            <input
              id="reg-password"
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          <div className="form-group">
            <label htmlFor="reg-confirm">Confirm Password</label>
            <input
              id="reg-confirm"
              type="password"
              className="input"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          {siteKey && (
            <div className="form-group">
              <div ref={turnstileRef} />
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%' }}
            disabled={loading}
          >
            {loading ? 'Registering...' : 'Register'}
          </button>
        </form>

        <p style={{ textAlign: 'center', marginTop: '1.5rem', color: 'var(--text-secondary)' }}>
          Already have an account?{' '}
          <Link href="/login" style={{ color: '#3b82f6' }}>
            Sign In
          </Link>
        </p>
      </div>
    </div>
  );
}
