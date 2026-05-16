'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';

export default function PendingPage() {
  const { isAuthenticated, isLoading, role, logout } = useAuth();
  const router = useRouter();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    } else if (!isLoading && role && role !== 'pending') {
      router.push('/dashboard');
    }
  }, [isAuthenticated, isLoading, role, router]);

  // Poll for approval every 30 seconds
  useEffect(() => {
    if (!isAuthenticated || role !== 'pending') return;

    pollRef.current = setInterval(async () => {
      try {
        const user = await api.getMe();
        if (user.role !== 'pending') {
          router.push('/dashboard');
        }
      } catch {
        // Ignore — user might be logged out or network down
      }
    }, 30000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isAuthenticated, role, router]);

  if (isLoading) {
    return (
      <div className="container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  return (
    <div className="container" style={{ maxWidth: '500px', marginTop: '100px' }}>
      <div className="card" style={{ textAlign: 'center' }}>
        <h1 style={{ marginBottom: '1rem' }}>Account Pending</h1>
        <p style={{ color: '#9ca3af', marginBottom: '2rem' }}>
          Your account is awaiting admin approval. You&apos;ll be able to use WrzDJ
          once an administrator approves your registration.
        </p>
        <button
          className="btn"
          style={{ background: '#333' }}
          onClick={logout}
        >
          Logout
        </button>
      </div>
    </div>
  );
}
