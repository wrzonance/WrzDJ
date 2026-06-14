'use client';

import { use, useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import type { SetDetail } from '@/lib/api-types';
import { ThemeToggle } from '@/components/ThemeToggle';
import BuilderBrandMenu from '../components/BuilderBrandMenu';
import BuilderWorkspace from '../components/BuilderWorkspace';
import ChatSidebar from '../components/ChatSidebar';
import PairingsOverlay from '../components/PairingsOverlay';
import BuilderSettingsModal, { type BuilderSettings } from '../components/BuilderSettingsModal';
import ConfirmActionDialog, { type ConfirmAction } from '../components/ConfirmActionDialog';
import HistoryControls from '../components/HistoryControls';
import PoolPanel from '../components/PoolPanel';
import { useSetDocumentHistory } from '../components/useSetDocumentHistory';
import TargetEditor from '../components/TargetEditor';
import {
  DEFAULT_AVG_TRANSITION_OVERLAP_SEC,
  type TargetProjection,
  type TargetSettings,
} from '../components/targetMath';
import SetActionsMenu from '../SetActionsMenu';
import styles from '../setbuilder.module.css';

type OpenPairingsEvent = CustomEvent<{ pairingId?: number | null }>;

const SETTINGS_KEY = 'wrzdj.setbuilder.settings';

const DEFAULT_SETTINGS: BuilderSettings = {
  suggestReplacements: true,
  confirmRecompute: true,
  confirmSlotRemoval: true,
  playOnDoubleClick: true,
  scrubOnCurveClick: true,
  showSlotMarkers: true,
  agentChimes: false,
  autoExpandPairings: true,
};

function readBuilderSettings(): BuilderSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function writeBuilderSettings(settings: BuilderSettings): void {
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    window.localStorage.setItem(
      'wrzdj.curve.suggestReplacements',
      String(settings.suggestReplacements),
    );
  } catch {
    // Best-effort browser preference.
  }
}

export default function BuilderPage({ params }: { params: Promise<{ setId: string }> }) {
  const { setId } = use(params);
  const numericSetId = Number(setId);
  const { isAuthenticated, isLoading, role } = useAuth();
  const router = useRouter();
  const [set, setSet] = useState<SetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [building, setBuilding] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [pairingsOpen, setPairingsOpen] = useState(false);
  const [pairingCount, setPairingCount] = useState(0);
  const [initialPairingId, setInitialPairingId] = useState<number | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [builderSettings, setBuilderSettings] = useState(DEFAULT_SETTINGS);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const confirmResolverRef = useRef<((value: boolean) => void) | null>(null);
  const history = useSetDocumentHistory(numericSetId);
  const [targetOpen, setTargetOpen] = useState(false);
  const [targetSettings, setTargetSettings] = useState<TargetSettings>({
    targetDurationSec: null,
    avgTransitionOverlapSec: DEFAULT_AVG_TRANSITION_OVERLAP_SEC,
  });
  const [targetProjection, setTargetProjection] = useState<TargetProjection | null>(null);
  const [savingTarget, setSavingTarget] = useState(false);

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
        .getSet(numericSetId)
        .then(setSet)
        .catch(() => setError('Set not found'));
    }
  }, [isAuthenticated, numericSetId]);

  useEffect(() => {
    setBuilderSettings(readBuilderSettings());
  }, []);

  const updateBuilderSettings = (next: BuilderSettings) => {
    setBuilderSettings(next);
    writeBuilderSettings(next);
  };

  const requestConfirmation = (action: ConfirmAction) =>
    new Promise<boolean>((resolve) => {
      confirmResolverRef.current?.(false);
      confirmResolverRef.current = (value: boolean) => resolve(value);
      setConfirmAction(action);
    });

  const closeConfirm = (value: boolean) => {
    confirmResolverRef.current?.(value);
    confirmResolverRef.current = null;
    setConfirmAction(null);
  };

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const runBuild = async () => {
    setBuilding(true);
    try {
      const result = await history.commit('Recompute set order', () => api.buildSet(numericSetId, true));
      setRefreshToken((v) => v + 1);
      setToast(`Pass 1 rebuilt ${result.slot_count} slots · ${result.iterations} refine steps`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to recompute set');
    } finally {
      setBuilding(false);
    }
  };

  const requestBuild = async () => {
    if (builderSettings.confirmRecompute) {
      const ok = await requestConfirmation({
        title: 'Recompute set order?',
        body: (
          <>
            <p>
              This reruns deterministic pass 1 and may overwrite unlocked manual order using the
              current pool, curve targets, transition scoring, and saved pairings.
            </p>
            <ul>
              <li>Locked slots stay fixed.</li>
              <li>Unlocked manual reorders may be replaced.</li>
              <li>Saved pairings are weighted into scoring.</li>
              <li>The action is undoable from the topbar or with Ctrl/Cmd+Z.</li>
            </ul>
          </>
        ),
        confirmLabel: 'Yes, recompute',
        kind: 'warning',
      });
      if (!ok) return;
    }
    void runBuild();
  };

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    const refreshCount = () => {
      api
        .getPairings(Number(setId))
        .then((state) => {
          if (!cancelled) setPairingCount(state.count);
        })
        .catch(() => {
          if (!cancelled) setPairingCount(0);
        });
    };
    const openPairings = (event: Event) => {
      const detail = (event as OpenPairingsEvent).detail;
      setInitialPairingId(detail?.pairingId ?? null);
      setPairingsOpen(true);
      refreshCount();
    };
    refreshCount();
    window.addEventListener('wrzdj:setbuilder-pairings-changed', refreshCount);
    window.addEventListener('wrzdj:open-pairings', openPairings);
    return () => {
      cancelled = true;
      window.removeEventListener('wrzdj:setbuilder-pairings-changed', refreshCount);
      window.removeEventListener('wrzdj:open-pairings', openPairings);
    };
  }, [isAuthenticated, setId]);

  useEffect(() => {
    if (!set) return;
    setTargetSettings({
      targetDurationSec: set.target_duration_sec,
      avgTransitionOverlapSec:
        set.avg_transition_overlap_sec ?? DEFAULT_AVG_TRANSITION_OVERLAP_SEC,
    });
  }, [set?.id, set?.target_duration_sec, set?.avg_transition_overlap_sec]);

  const targetDirty =
    !!set &&
    (targetSettings.targetDurationSec !== set.target_duration_sec ||
      targetSettings.avgTransitionOverlapSec !==
        (set.avg_transition_overlap_sec ?? DEFAULT_AVG_TRANSITION_OVERLAP_SEC));

  const undoTarget = () => {
    if (!set) return;
    setTargetSettings({
      targetDurationSec: set.target_duration_sec,
      avgTransitionOverlapSec:
        set.avg_transition_overlap_sec ?? DEFAULT_AVG_TRANSITION_OVERLAP_SEC,
    });
  };

  const saveTarget = async () => {
    if (!set || !targetDirty) return;
    setSavingTarget(true);
    try {
      const updated = await api.updateSetTargetSettings(
        set.id,
        targetSettings.targetDurationSec,
        targetSettings.avgTransitionOverlapSec,
      );
      setSet(updated);
    } finally {
      setSavingTarget(false);
    }
  };

  const handleProjectionChange = useCallback((projection: TargetProjection) => {
    setTargetProjection(projection);
  }, []);

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
        <span className={styles.topbarLeft}>
          <Link
            href="/setbuilder"
            className="btn btn-sm"
            style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
          >
            ← Sets
          </Link>
          <BuilderBrandMenu
            name={set?.name ?? 'Loading…'}
            isDirty={history.isDirty}
            isSaving={history.isSaving}
            saveError={history.saveError}
            lastSavedAt={history.lastSavedAt}
            onSave={() => void history.saveNow()}
            onSettings={() => setSettingsOpen(true)}
          />
        </span>
        <span className={styles.topbarActions}>
          <span className={styles.topbarStats}>
            {targetProjection ? (
              <>
                <span>
                  <strong>{targetProjection.slotCount}</strong> tracks
                </span>
                <span className={styles.statDot} />
              </>
            ) : null}
            {set && (
              <TargetEditor
                settings={targetSettings}
                projection={targetProjection}
                dirty={targetDirty}
                saving={savingTarget}
                open={targetOpen}
                onOpenChange={setTargetOpen}
                onSettingsChange={setTargetSettings}
                onSave={saveTarget}
                onUndo={undoTarget}
              />
            )}
          </span>
          <HistoryControls
            undoDepth={history.undoDepth}
            redoDepth={history.redoDepth}
            nextUndoLabel={history.nextUndoLabel}
            nextRedoLabel={history.nextRedoLabel}
            onUndo={() => void history.undo()}
            onRedo={() => void history.redo()}
            onSettings={() => setSettingsOpen(true)}
            isSaving={history.isSaving}
          />
          <button
            type="button"
            className={styles.topbarPairingsBtn}
            aria-label={`Open pairings (${pairingCount})`}
            onClick={() => {
              setInitialPairingId(null);
              setPairingsOpen(true);
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M10.5 13.5 13.5 10.5M8.5 17.5H7.8a4.8 4.8 0 0 1 0-9.6h3.4M12.8 16.1h3.4a4.8 4.8 0 1 0 0-9.6h-.7"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.8"
              />
            </svg>
            Pairings
            <span className={styles.topbarPairingsBadge}>{pairingCount}</span>
          </button>
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
            onClick={() => void requestBuild()}
            disabled={building}
          >
            {building ? 'Recomputing...' : 'Recompute'}
          </button>
          <ThemeToggle />
        </span>
      </div>

      <div className={`${styles.workspace} ${chatOpen ? styles.chatOpen : styles.chatClosed}`}>
        <section className={`${styles.panel} ${styles.panelPool}`} aria-label="Pool">
          <PoolPanel
            setId={numericSetId}
            snapshot={history.snapshot}
            snapshotVersion={history.snapshotVersion}
            commit={history.commit}
            confirmRemovals={builderSettings.confirmSlotRemoval}
            requestConfirmation={requestConfirmation}
          />
        </section>

        <BuilderWorkspace
          setId={numericSetId}
          refreshToken={refreshToken}
          snapshot={history.snapshot}
          snapshotVersion={history.snapshotVersion}
          commit={history.commit}
          suggestReplacements={builderSettings.suggestReplacements}
          onSuggestReplacementsChange={(checked) =>
            updateBuilderSettings({ ...builderSettings, suggestReplacements: checked })
          }
          confirmRecompute={builderSettings.confirmRecompute}
          requestConfirmation={requestConfirmation}
          targetSettings={targetSettings}
          onProjectionChange={handleProjectionChange}
        />

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
      {toast && (
        <div className={styles.poolToast} role="status" aria-live="polite">
          {toast}
        </div>
      )}

      <PairingsOverlay
        setId={Number(setId)}
        open={pairingsOpen}
        initialPairingId={initialPairingId}
        onClose={() => setPairingsOpen(false)}
        onChanged={setPairingCount}
        onJumpSlot={(idx) =>
          window.dispatchEvent(
            new CustomEvent('wrzdj:setbuilder-jump-slot', { detail: { idx } }),
          )
        }
      />
      <BuilderSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        autosave={history.autosave}
        onAutosaveChange={history.setAutosave}
        settings={builderSettings}
        onSettingsChange={updateBuilderSettings}
      />
      <ConfirmActionDialog
        action={confirmAction}
        onCancel={() => closeConfirm(false)}
        onConfirm={() => closeConfirm(true)}
      />
      {history.toast && (
        <div className={styles.poolToast} role="status">
          {history.toast}
        </div>
      )}
    </div>
  );
}
