'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import { api } from '@/lib/api';

export function ConfirmEmailContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const token = searchParams.get('token');
    if (!token) {
      setStatus('error');
      setErrorMessage('No confirmation token provided.');
      return;
    }
    api
      .confirmEmailChange(token)
      .then(() => {
        setStatus('success');
        setTimeout(() => router.push('/account'), 2000);
      })
      .catch((err: unknown) => {
        setStatus('error');
        setErrorMessage(err instanceof Error ? err.message : 'Confirmation failed.');
      });
  }, [searchParams, router]);

  return (
    <main style={{ maxWidth: '480px', margin: '4rem auto', padding: '2rem 1rem', textAlign: 'center' }}>
      {status === 'loading' && (
        <p style={{ color: '#aaa' }}>Verifying your email address…</p>
      )}
      {status === 'success' && (
        <>
          <p style={{ color: '#4ade80', fontSize: '1.1rem', marginBottom: '0.5rem' }}>
            Email address updated!
          </p>
          <p style={{ color: '#888', fontSize: '0.875rem' }}>
            Redirecting to account settings…
          </p>
        </>
      )}
      {status === 'error' && (
        <>
          <p style={{ color: '#f87171', fontSize: '1.1rem', marginBottom: '0.5rem' }}>
            Confirmation failed
          </p>
          <p style={{ color: '#888', fontSize: '0.875rem', marginBottom: '1.5rem' }}>
            {errorMessage}
          </p>
          <Link href="/account" style={{ color: '#818cf8' }}>
            Return to account settings
          </Link>
        </>
      )}
    </main>
  );
}

export default function ConfirmEmailPage() {
  return <ConfirmEmailContent />;
}
