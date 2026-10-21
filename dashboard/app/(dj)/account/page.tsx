'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import AiProvidersSection from '@/app/(dj)/account/components/AiProvidersSection';
import AppleMusicAccountCard from '@/app/(dj)/account/components/AppleMusicAccountCard';
import PasswordChangeSection from '@/app/(dj)/account/components/PasswordChangeSection';
import EmailChangeSection from '@/app/(dj)/account/components/EmailChangeSection';
import GuestExperienceSection from '@/app/(dj)/account/components/GuestExperienceSection';
import { PageControls } from '@/components/PageControls';
import { LOCALES, type Locale } from '@/lib/locales';
import { useLocale } from '@/lib/locale';

export default function AccountPage() {
  const { locale, setLocale, messages } = useLocale();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  const [emailPending, setEmailPending] = useState<string | null>(null);
  const [frictionlessDefault, setFrictionlessDefault] = useState(false);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, isLoading, router]);

  useEffect(() => {
    if (isAuthenticated) {
      let isActive = true;
      api.getMe()
        .then(user => {
          if (!isActive) return;
          setEmailPending(prev => prev ?? (user.pending_email ?? null));
          setFrictionlessDefault(user.frictionless_join_default);
        })
        .catch(() => {});
      return () => { isActive = false; };
    }
  }, [isAuthenticated]);

  if (isLoading || !isAuthenticated) return null;

  return (
    <main style={{ maxWidth: '720px', margin: '0 auto', padding: '2rem 1rem' }}>
      <PageControls />
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        <Link href="/dashboard" style={{ color: 'var(--text-secondary)', textDecoration: 'none', fontSize: '0.875rem' }}>
          ← Dashboard
        </Link>
        <h1 style={{ margin: 0, fontSize: '1.5rem' }}>Account Settings</h1>
      </div>

      <div style={{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem', marginBottom: '1.5rem' }}>
        <h2 lang={locale} style={{ marginTop: 0, marginBottom: '0.75rem', fontSize: '1.1rem' }}>{messages.language.heading}</h2>
        <label lang={locale} htmlFor="dashboard-language" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
          {messages.language.label}
        </label>
        <select
          id="dashboard-language"
          className="input"
          value={locale}
          onChange={event => setLocale(event.target.value as Locale)}
          style={{ width: '100%', marginBottom: '1.5rem', boxSizing: 'border-box' }}
        >
          <option lang={locale} value={LOCALES[0]}>{messages.language.english}</option>
          <option lang={locale} value={LOCALES[1]}>{messages.language.spanish}</option>
        </select>
      </div>

      <PasswordChangeSection />
      <EmailChangeSection pendingEmail={emailPending} onPendingEmailChange={setEmailPending} />

      <div style={{ background: 'var(--card)', borderRadius: '0.75rem', padding: '1.5rem', marginTop: '1.5rem' }}>
        <AiProvidersSection />
      </div>

      <AppleMusicAccountCard />

      <GuestExperienceSection initialFrictionlessDefault={frictionlessDefault} />
    </main>
  );
}
