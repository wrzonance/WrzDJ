'use client';

import { use, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import type { SetDetail } from '@/lib/api-types';
import styles from '../setbuilder.module.css';

export default function BuilderPage({ params }: { params: Promise<{ setId: string }> }) {
  const { setId } = use(params);
  const { isAuthenticated, isLoading, role } = useAuth();
  const router = useRouter();
  const [set, setSet] = useState<SetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    } else if (!isLoading && role === 'pending') {
      router.push('/pending');
    }
  }, [isAuthenticated, isLoading, role, router]);

  useEffect(() => {
    if (isAuthenticated) {
      api
        .getSet(Number(setId))
        .then(setSet)
        .catch(() => setError('Set not found'));
    }
  }, [isAuthenticated, setId]);

  if (isLoading || !isAuthenticated) {
    return (
      <div className="container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container">
        <div className="card" style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--color-danger)' }}>{error}</p>
          <Link
            href="/setbuilder"
            className="btn btn-primary"
            style={{ marginTop: '1rem', textDecoration: 'none' }}
          >
            Back to Sets
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className={styles.topbar}>
        <Link
          href="/setbuilder"
          className="btn btn-sm"
          style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
        >
          ← Sets
        </Link>
        <span className={styles.topbarTitle}>{set?.name ?? 'Loading…'}</span>
        <span style={{ width: 60 }} />
      </div>

      <div className={styles.workspace}>
        <section className={`${styles.panel} ${styles.panelPool}`} aria-label="Pool">
          <div className={styles.panelHeader}>Pool</div>
          <div className={styles.panelBody}>Candidate tracks will appear here.</div>
        </section>

        <section className={`${styles.panel} ${styles.panelCurve}`} aria-label="Curve">
          <div className={styles.panelHeader}>Curve</div>
          <div className={styles.panelBody}>Energy curve editor coming soon.</div>
        </section>

        <section className={`${styles.panel} ${styles.panelTimeline}`} aria-label="Timeline">
          <div className={styles.panelHeader}>Timeline</div>
          <div className={styles.panelBody}>Ordered set timeline coming soon.</div>
        </section>

        <section className={`${styles.panel} ${styles.panelChat}`} aria-label="Chat">
          <div className={styles.panelHeader}>Chat</div>
          <div className={styles.panelBody}>Agent chat coming soon.</div>
        </section>
      </div>
    </div>
  );
}
