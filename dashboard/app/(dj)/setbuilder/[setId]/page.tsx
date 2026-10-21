'use client';

import { use, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useDjAccess } from '@/lib/use-dj-access';
import { api } from '@/lib/api';
import type { SetDetail } from '@/lib/api/types';
import { ThemeToggle } from '@/components/ThemeToggle';
import BuilderBrandMenu from '../components/BuilderBrandMenu';
import BuilderWorkspace from '../components/BuilderWorkspace';
import ChatSidebar from '../components/chat/ChatSidebar';
import MobileAgentOverlay from '../components/MobileAgentOverlay';
import { useIsMobile } from '../components/useIsMobile';
import PairingsOverlay from '../components/pairings/PairingsOverlay';
import PlaybackReportOverlay from '../components/PlaybackReportOverlay';
import BuilderSettingsModal, { type BuilderSettings } from '../components/BuilderSettingsModal';
import ConfirmActionDialog, { type ConfirmAction } from '../components/ConfirmActionDialog';
import HistoryControls from '../components/HistoryControls';
import PoolPanel from '../components/pool/PoolPanel';
import { useSetDocumentHistory } from '../components/useSetDocumentHistory';
import { useBuilderPairings } from './useBuilderPairings';
import { useSetTargetSettings } from './useSetTargetSettings';
import { useBuilderBuildWorkflow } from './useBuilderBuildWorkflow';
import TargetEditor from '../components/TargetEditor';
import { formatDuration } from '../components/curve/targetMath';
import { poolRuntimeSec, projectedSlotCount } from '../components/pool/poolRuntime';
import SetActionsMenu from '../SetActionsMenu';
import styles from '../setbuilder.module.css';
import poolStyles from '../setbuilder-pool.module.css';

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
  return <BuilderPageForSet key={setId} setId={setId} />;
}

function BuilderPageForSet({ setId }: { setId: string }) {
  const numericSetId = Number(setId);
  const { isAuthenticated, isLoading, canAccess } = useDjAccess();
  const isMobile = useIsMobile();
  // Defer mounting either chat surface until after hydration so a mobile client
  // never briefly mounts the desktop sidebar (and its agent fetches) before
  // `useIsMobile` resolves. The grid already reserves the chat column, so this
  // adds no layout shift on desktop.
  const [chatSurfaceReady, setChatSurfaceReady] = useState(false);
  const [set, setSet] = useState<SetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const [playbackOpen, setPlaybackOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [builderSettings, setBuilderSettings] = useState(DEFAULT_SETTINGS);
  const historyEnabled = canAccess;
  const history = useSetDocumentHistory(numericSetId, { enabled: historyEnabled });
  const refreshWorkspace = useCallback(() => {
    setRefreshToken((current) => current + 1);
  }, []);
  const pairings = useBuilderPairings(numericSetId, historyEnabled, refreshWorkspace);
  const [targetOpen, setTargetOpen] = useState(false);
  const target = useSetTargetSettings(set, setSet, setToast);
  const { settings: targetSettings, projection: targetProjection } = target;

  const onBuildComplete = useCallback((result: Awaited<ReturnType<typeof api.buildSet>>) => {
    setRefreshToken((value) => value + 1);
    setToast(`Pass 1 rebuilt ${result.slot_count} slots · ${result.iterations} refine steps`);
  }, []);
  const onBuildError = useCallback((message: string) => setError(message), []);
  const {
    building,
    confirmAction,
    requestBuild: runBuildWorkflow,
    requestConfirmation,
    closeConfirmation,
  } = useBuilderBuildWorkflow({
    setId: numericSetId,
    commit: history.commit,
    onBuildComplete,
    onBuildError,
  });

  useEffect(() => {
    setChatSurfaceReady(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (canAccess) {
      api
        .getSet(numericSetId)
        .then((loadedSet) => {
          if (!cancelled) setSet(loadedSet);
        })
        .catch(() => {
          if (!cancelled) setError('Set not found');
        });
    }
    return () => { cancelled = true; };
  }, [canAccess, numericSetId]);

  useEffect(() => {
    setBuilderSettings(readBuilderSettings());
  }, []);

  const updateBuilderSettings = (next: BuilderSettings) => {
    setBuilderSettings(next);
    writeBuilderSettings(next);
  };

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const requestBuild = () => {
    if (builderSettings.confirmRecompute) {
      const snapshotSlots = history.snapshot?.slots ?? [];
      const lockedCount = snapshotSlots.filter((slot) => slot.locked).length;
      const unlockedCount = Math.max(0, snapshotSlots.length - lockedCount);
      // Pool runtime vs. target → resulting slot count, computed BEFORE generation
      // (#538) so the DJ sees that a big pool becomes a length-gated set, never a
      // runaway "12-hour" dump. Uses the snapshot the page already holds.
      const poolTracks = history.snapshot?.pool?.tracks ?? [];
      const poolSize = poolTracks.length;
      const poolRuntime = poolRuntimeSec(poolTracks);
      const builtSlots = projectedSlotCount(poolTracks, targetSettings);
      const remaining = Math.max(0, poolSize - builtSlots);
      const targetLabel = formatDuration(targetSettings.targetDurationSec);
      const confirmation: ConfirmAction = {
        title: 'Recompute set order?',
        body: (
          <>
            {poolSize > 0 && (
              <p style={{ fontWeight: 600 }}>
                Pool: {poolSize} {poolSize === 1 ? 'track' : 'tracks'} (~
                {formatDuration(poolRuntime)}).{' '}
                {targetSettings.targetDurationSec
                  ? `Target ${targetLabel} → will build ~${builtSlots} ${
                      builtSlots === 1 ? 'slot' : 'slots'
                    }`
                  : `No target → capped build of ~${builtSlots} ${
                      builtSlots === 1 ? 'slot' : 'slots'
                    }`}
                ; the remaining {remaining} stay in the pool as candidates.
              </p>
            )}
            <p>
              This reruns deterministic pass 1 and may overwrite unlocked manual order using the
              current pool, curve targets, transition scoring, and saved pairings.
            </p>
            <ul>
              <li>
                {snapshotSlots.length > 0
                  ? `${lockedCount} locked ${lockedCount === 1 ? 'slot stays' : 'slots stay'} fixed.`
                  : 'Locked slots stay fixed.'}
              </li>
              <li>
                {snapshotSlots.length > 0
                  ? `${unlockedCount} unlocked ${
                      unlockedCount === 1 ? 'slot may be' : 'slots may be'
                    } replaced or reordered.`
                  : 'Unlocked manual reorders may be replaced.'}
              </li>
              <li>Saved pairings are weighted into scoring.</li>
              <li>The action is undoable from the topbar or with Ctrl/Cmd+Z.</li>
            </ul>
          </>
        ),
        confirmLabel: 'Yes, recompute',
        kind: 'warning',
      };
      void runBuildWorkflow(confirmation);
      return;
    }
    void runBuildWorkflow();
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
                dirty={target.dirty}
                saving={target.saving}
                open={targetOpen}
                onOpenChange={setTargetOpen}
                onSettingsChange={target.update}
                onSave={target.save}
                onUndo={target.undo}
              />
            )}
            {target.error ? (
              <span className={styles.targetSaveError} role="alert">
                {target.error}
              </span>
            ) : null}
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
            aria-label={`Open pairings (${pairings.count})`}
            onClick={() => pairings.openPairings()}
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
            <span className={styles.topbarPairingsBadge}>{pairings.count}</span>
          </button>
          {pairings.hasRefreshError && (
            <>
              <span className={styles.targetSaveError} role="alert">
                Could not refresh saved pairings.
              </span>
              <button
                type="button"
                className="btn btn-sm"
                aria-label="Retry pairing count"
                onClick={() => void pairings.refresh()}
              >
                Retry
              </button>
            </>
          )}
          {set?.event_id != null && (
            <button
              type="button"
              className={styles.topbarReportBtn}
              aria-label="Open playback report"
              onClick={() => setPlaybackOpen(true)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M4 19V5m0 14h16M8 16V9m4 7V6m4 10v-4"
                  fill="none"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="1.8"
                />
              </svg>
              Playback report
            </button>
          )}
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
            onClick={requestBuild}
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
          jumpSlotRequest={pairings.jumpSlotRequest}
          onOpenPairings={pairings.openPairings}
          onPairingsChanged={pairings.handlePairingsChanged}
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
          onProjectionChange={target.updateProjection}
        />

        {chatSurfaceReady && !isMobile && (
          <div className={styles.panelChat}>
            <ChatSidebar
              setId={Number(setId)}
              open={chatOpen}
              onToggle={() => setChatOpen((open) => !open)}
              refreshToken={refreshToken}
              onMutationApplied={() => setRefreshToken((v) => v + 1)}
              commit={historyEnabled ? history.commit : undefined}
            />
          </div>
        )}
      </div>
      {chatSurfaceReady && isMobile && (
        <MobileAgentOverlay
          setId={Number(setId)}
          refreshToken={refreshToken}
          onMutationApplied={() => setRefreshToken((v) => v + 1)}
          commit={historyEnabled ? history.commit : undefined}
        />
      )}
      {toast && (
        <div className={poolStyles.poolToast} role="status" aria-live="polite">
          {toast}
        </div>
      )}

      <PairingsOverlay
        setId={Number(setId)}
        open={pairings.open}
        initialPairingId={pairings.initialPairingId}
        onClose={pairings.closePairings}
        onChanged={pairings.handlePairingsChanged}
        onJumpSlot={pairings.jumpToSlot}
      />
      {set?.event_id != null && (
        <PlaybackReportOverlay
          setId={numericSetId}
          open={playbackOpen}
          onClose={() => setPlaybackOpen(false)}
          onApplied={() => pairings.handlePairingsChanged()}
        />
      )}
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
        onCancel={() => closeConfirmation(false)}
        onConfirm={() => closeConfirmation(true)}
      />
      {history.toast && (
        <div className={poolStyles.poolToast} role="status">
          {history.toast}
        </div>
      )}
    </div>
  );
}
