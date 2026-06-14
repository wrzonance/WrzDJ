'use client';

import { use, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import type { SetDetail } from '@/lib/api-types';
import { ThemeToggle } from '@/components/ThemeToggle';
import BuilderWorkspace from '../components/BuilderWorkspace';
import ChatSidebar from '../components/ChatSidebar';
import PoolPanel from '../components/PoolPanel';
import SetActionsMenu from '../SetActionsMenu';
import styles from '../setbuilder.module.css';

export default function BuilderPage({ params }: { params: Promise<{ setId: string }> }) {
  const { setId } = use(params);
  const { isAuthenticated, isLoading, role } = useAuth();
  const router = useRouter();
  const [set, setSet] = useState<SetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [confirmBuild, setConfirmBuild] = useState(false);
  const [building, setBuilding] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

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

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const runBuild = async () => {
    setBuilding(true);
    try {
      const result = await api.buildSet(Number(setId), true);
      setRefreshToken((v) => v + 1);
      setToast(`Pass 1 rebuilt ${result.slot_count} slots · ${result.iterations} refine steps`);
      setConfirmBuild(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to recompute set');
    } finally {
      setBuilding(false);
    }
  };

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
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}>
          {set && (
            <SetActionsMenu
              set={set}
              onShareChanged={(token) =>
                setSet((prev) => (prev ? { ...prev, share_token: token } : prev))
              }
              onSetUpdated={(patch) => setSet((prev) => (prev ? { ...prev, ...patch } : prev))}
            />
          )}
          <button
            className="btn btn-sm"
            title="Re-run deterministic pass 1"
            onClick={() => setConfirmBuild(true)}
          >
            Recompute
          </button>
          <ThemeToggle />
        </span>
      </div>

      <div className={`${styles.workspace} ${chatOpen ? styles.chatOpen : styles.chatClosed}`}>
        <section className={`${styles.panel} ${styles.panelPool}`} aria-label="Pool">
          <PoolPanel setId={Number(setId)} />
        </section>

        <BuilderWorkspace setId={Number(setId)} refreshToken={refreshToken} />

        <div className={styles.panelChat}>
          <ChatSidebar
            setId={Number(setId)}
            open={chatOpen}
            onToggle={() => setChatOpen((open) => !open)}
            refreshToken={refreshToken}
            onMutationApplied={() => setRefreshToken((v) => v + 1)}
          />
        </div>
      </div>

      {confirmBuild && (
        <div className={styles.confirmWrap}>
          <div className={styles.confirmBackdrop} onClick={() => setConfirmBuild(false)} />
          <div className={styles.confirmDialog} role="dialog" aria-modal="true">
            <div className={styles.confirmHeader}>
              <div className={styles.confirmIcon}>!</div>
              <div className={styles.confirmTitle}>Recompute set order?</div>
            </div>
            <div className={styles.confirmBody}>
              <p>
                This reruns deterministic pass 1 and may overwrite unlocked manual order using
                the current pool, curve targets, transition scoring, and saved pairings.
              </p>
              <ul>
                <li>Locked slots stay fixed.</li>
                <li>Unlocked manual reorders may be replaced.</li>
                <li>Saved pairings are weighted into scoring.</li>
                <li>This action is designed to be undoable once undo/save lands.</li>
              </ul>
            </div>
            <div className={styles.confirmFooter}>
              <button className="btn" onClick={() => setConfirmBuild(false)} disabled={building}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={runBuild} disabled={building}>
                {building ? 'Recomputing...' : 'Yes, recompute'}
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className={styles.builderToast}>{toast}</div>}
    </div>
  );
}
