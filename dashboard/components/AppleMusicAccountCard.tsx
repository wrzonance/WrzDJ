'use client';

import { useEffect, useState } from 'react';

import { api, type AppleMusicStatus } from '@/lib/api';
import { authorizeAppleMusic } from '@/lib/apple-music-auth';

export default function AppleMusicAccountCard() {
  const [status, setStatus] = useState<AppleMusicStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    api.getAppleMusicStatus()
      .then(value => { if (active) setStatus(value); })
      .catch(() => { if (active) setError('Could not load Apple Music account status.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const connect = async () => {
    setBusy(true);
    setError('');
    try {
      const tokenResponse = await api.getAppleMusicDeveloperToken();
      const musicUserToken = await authorizeAppleMusic(tokenResponse.developer_token);
      setStatus(await api.linkAppleMusicAccount(musicUserToken));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not connect Apple Music.');
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    setError('');
    try {
      await api.disconnectAppleMusicAccount();
      setStatus(current => current ? {
        ...current,
        linked: false,
        requires_reauthorization: false,
        storefront: null,
      } : current);
    } catch {
      setError('Could not disconnect Apple Music.');
    } finally {
      setBusy(false);
    }
  };

  const message = !status?.configured
    ? 'Apple Music is not configured for this deployment.'
    : status.requires_reauthorization
      ? 'Apple Music authorization needs to be renewed.'
      : status.linked
        ? `Connected to Apple Music (${status.storefront?.toUpperCase() ?? 'storefront unknown'}).`
        : 'Connect Apple Music to enable account-specific features.';

  return (
    <section
      aria-labelledby="apple-music-account-heading"
      style={{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem', marginTop: '1.5rem' }}
    >
      <h2 id="apple-music-account-heading" style={{ marginTop: 0, marginBottom: '0.5rem', fontSize: '1.1rem' }}>
        Apple Music
      </h2>
      <p role="status" style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0 0 1rem' }}>
        {loading ? 'Loading account status…' : message}
      </p>
      {error && <p role="alert" style={{ color: 'var(--color-danger)', fontSize: '0.875rem' }}>{error}</p>}
      {!loading && status?.linked ? (
        <button className="btn" onClick={disconnect} disabled={busy}>
          {busy ? 'Working…' : 'Disconnect Apple Music'}
        </button>
      ) : (
        <button
          className="btn btn-primary"
          onClick={connect}
          disabled={loading || busy || !status?.configured}
        >
          {busy ? 'Connecting…' : status?.requires_reauthorization ? 'Reconnect Apple Music' : 'Connect Apple Music'}
        </button>
      )}
    </section>
  );
}
