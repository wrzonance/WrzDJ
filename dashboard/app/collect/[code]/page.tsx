'use client';

import { useParams } from 'next/navigation';
import { useMemo, useState } from 'react';
import {
  api,
  CollectLeaderboardRow,
  PUBLIC_PAGE_MAX,
} from '../../../lib/api';
import { useGuestIdentity } from '../../../lib/use-guest-identity';
import { useHumanVerification } from '@/lib/use-human-verification';
import { IdentityBar } from '../../../components/IdentityBar';
import { NicknameGate, GateResult } from '../../../components/NicknameGate';
import EmailGate from '../../../components/EmailGate';
import EmailRecoveryButton from '../../../components/EmailRecoveryButton';
import EmailRecoveryModal from '../../../components/EmailRecoveryModal';
import HumanVerificationOverlay from '../../../components/HumanVerificationOverlay';
import CollectDetailSheet from './components/CollectDetailSheet';
import CollectSearchSheet from './components/CollectSearchSheet';
import LeaderboardTabs from './components/LeaderboardTabs';
import MyPicksPanel from './components/MyPicksPanel';
import SubmitBar from './components/SubmitBar';
import { useCollectPolling } from './useCollectPolling';
import { useCollectSearch } from './useCollectSearch';
import { useCollectSubmission } from './useCollectSubmission';

/* Leaderboard is a growing window: "Load more" grows displayLimit and every
   poll re-fetches [0, displayLimit) from offset 0. This keeps live vote
   updates correct without client-side dedup or offset-drift bugs. */
const PAGE_SIZE = 100;

export default function CollectPage() {
  const params = useParams<{ code: string }>();
  const code = params?.code ?? '';
  const { reconcileHint, refresh: refreshIdentity } = useGuestIdentity();
  const { state: humanState, reverify, retry, widgetContainerRef } = useHumanVerification();

  const [tab, setTab] = useState<'trending' | 'all'>('all');
  const [displayLimit, setDisplayLimit] = useState(PAGE_SIZE);
  const [emailVerified, setEmailVerified] = useState(false);
  const [nickname, setNickname] = useState<string | null>(null);
  const [profile, setProfile] = useState<{
    submission_count: number;
    submission_cap: number;
  } | null>(null);

  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [gateComplete, setGateComplete] = useState(false);
  const { event, leaderboard, myPicks, error, setLeaderboard } = useCollectPolling({
    code,
    tab,
    displayLimit,
    gateComplete,
    emailVerified,
    humanState,
    reverify,
  });

  // Canonical voted set covers upvotes and the guest's own submissions.
  const votedIds = new Set<number>([
    ...(myPicks?.voted_request_ids ?? []),
    ...(myPicks?.submitted ?? []).map((s) => s.id),
  ]);
  const handleGateComplete = (result: GateResult) => {
    setNickname(result.nickname || null);
    setEmailVerified(result.emailVerified);
    setProfile({ submission_count: result.submissionCount, submission_cap: result.submissionCap });
    setGateComplete(true);
  };

  const [detailRow, setDetailRow] = useState<CollectLeaderboardRow | null>(null);
  const [detailVoted, setDetailVoted] = useState(false);
  const [detailVoteError, setDetailVoteError] = useState<string | null>(null);

  const search = useCollectSearch({ code });
  const submission = useCollectSubmission({
    code,
    nickname,
    tab,
    displayLimit,
    setProfile,
    setLeaderboard,
    reverify,
    onSuccess: search.closeSearch,
  });
  const openSearch = () => {
    submission.resetSubmissionSession();
    search.openSearch();
  };
  const closeSearch = () => {
    submission.resetSubmissionSession();
    search.closeSearch();
  };

  const leaderboardAvgBpm = useMemo(() => {
    const withBpm = (leaderboard?.requests ?? []).filter((r) => r.bpm != null);
    return withBpm.length > 0
      ? withBpm.reduce((s, r) => s + (r.bpm ?? 0), 0) / withBpm.length
      : 128;
  }, [leaderboard]);

  // Single wrapper applied to every render path. Renders the overlay until
  // human verification is established; children only mount when verified.
  const wrap = (content: React.ReactNode) => (
    <HumanVerificationOverlay
      state={humanState}
      widgetContainerRef={widgetContainerRef}
      onRetry={retry}
    >
      {content}
    </HumanVerificationOverlay>
  );

  if (!gateComplete) {
    return wrap(
      <NicknameGate code={code} onComplete={handleGateComplete} reverify={reverify} />,
    );
  }

  if (error) {
    return wrap(
      <main className="collect-page">
        <div className="collect-container">
          <div className="collect-error">Error: {error}</div>
        </div>
      </main>,
    );
  }
  if (!event) {
    return wrap(
      <main className="collect-page">
        <div className="loading">Loading…</div>
      </main>,
    );
  }

  const bannerNode = event.banner_url ? (
    <div className="join-banner-bg">
      <img src={event.banner_url} alt="" />
    </div>
  ) : null;

  if (event.phase === 'pre_announce') {
    const opens = event.collection_opens_at ? new Date(event.collection_opens_at) : null;
    return wrap(
      <main className="collect-page tower">
        {bannerNode}
        <div className="collect-container">
          <div className="collect-preannounce">
            <div className="collect-phase-badge pre-announce">
              <span>🎟️</span>
              <span>Pre-event voting</span>
            </div>
            <h1 className="collect-title">{event.name}</h1>
            <div className="collect-preannounce-count">{formatCountdown(opens)}</div>
            <p className="collect-countdown">until voting opens</p>
          </div>
        </div>
      </main>,
    );
  }

  const liveStarts = event.live_starts_at ? new Date(event.live_starts_at) : null;
  const accent = '#00f0ff';
  const accent2 = '#ff2bd6';
  const surface = 'rgba(255,255,255,0.04)';
  const border = 'rgba(255,255,255,0.08)';
  const subFg = 'rgba(255,255,255,0.5)';

  return wrap(
    <EmailGate verified={emailVerified} onVerified={() => setEmailVerified(true)}>
    <main className="collect-page tower">
      {/* Ambient glows */}
      <div style={{ position: 'fixed', top: 40, left: -80, width: 280, height: 280, borderRadius: '50%', background: `radial-gradient(circle, ${accent2}28, transparent 70%)`, filter: 'blur(40px)', pointerEvents: 'none', zIndex: 0 }} />
      <div style={{ position: 'fixed', bottom: 40, right: -80, width: 280, height: 280, borderRadius: '50%', background: `radial-gradient(circle, ${accent}28, transparent 70%)`, filter: 'blur(40px)', pointerEvents: 'none', zIndex: 0 }} />

      {nickname && (
        <IdentityBar
          forceDark
          nickname={nickname}
          emailVerified={emailVerified}
          onVerified={() => setEmailVerified(true)}
          picksLabel={
            event.submission_cap_per_guest === 0
              ? 'Unlimited picks'
              : `${profile?.submission_count ?? 0} of ${event.submission_cap_per_guest} picks used`
          }
        />
      )}
      {bannerNode}
      <div className="collect-container" style={{ position: 'relative', zIndex: 1 }}>
        <header style={{ padding: '10px 0 14px' }}>
          {/* Phase badge */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '5px 11px', borderRadius: 99,
            background: `${accent}14`, border: `1px solid ${accent}40`,
            fontFamily: 'var(--font-mono, monospace)', fontSize: 11.6, fontWeight: 700,
            color: accent, letterSpacing: 1.2, marginBottom: 10,
          }}>
            <span>🎟️</span>
            <span>Pre-event voting is open</span>
          </div>

          {/* Top bar row */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <h1 style={{
                fontSize: 31.5, fontWeight: 800, letterSpacing: -0.7, lineHeight: 1.05,
                margin: 0, color: '#fff',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>
                {event.name}
              </h1>
              {liveStarts && (
                <p style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 12.1, color: subFg, marginTop: 6, letterSpacing: 0.5 }}>
                  Live show in <strong style={{ color: '#fff' }}>{formatCountdown(liveStarts)}</strong>
                </p>
              )}
            </div>
            <div style={{ padding: '5px 10px', borderRadius: 7, border: `1px solid ${border}`, flexShrink: 0 }}>
              <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 15.7, fontWeight: 800, color: '#fff' }}>
                {leaderboard?.total ?? 0}
              </span>
              <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 9, color: subFg, letterSpacing: 1.2, marginTop: 2 }}>
                SONGS
              </div>
            </div>
          </div>
        </header>

        <EmailRecoveryButton
          reconcileHint={reconcileHint}
          emailVerified={emailVerified}
          onOpen={() => setRecoveryOpen(true)}
        />

        <section className="collect-section">
          <LeaderboardTabs
            rows={leaderboard?.requests ?? []}
            tab={tab}
            onTabChange={(t) => { setTab(t); setDisplayLimit(PAGE_SIZE); }}
            onVote={(id) => api.voteCollectRequest(code, id, reverify)}
            votedIds={votedIds}
            onRowClick={(row) => {
              setDetailRow(row);
              setDetailVoted(false);
              setDetailVoteError(null);
            }}
          />
          {(leaderboard?.requests.length ?? 0) < Math.min(leaderboard?.total ?? 0, PUBLIC_PAGE_MAX) && (
            <button
              type="button"
              onClick={() => setDisplayLimit((d) => Math.min(d + PAGE_SIZE, PUBLIC_PAGE_MAX))}
              style={{
                width: '100%', marginTop: 10, padding: '13px 16px', borderRadius: 12,
                background: surface, border: `1px solid ${border}`, color: '#fff',
                fontFamily: 'var(--font-mono, monospace)', fontSize: 12.5, fontWeight: 700,
                letterSpacing: 1.2, cursor: 'pointer',
              }}
            >
              LOAD MORE · {Math.max(Math.min(leaderboard?.total ?? 0, PUBLIC_PAGE_MAX) - (leaderboard?.requests.length ?? 0), 0)} MORE
            </button>
          )}
        </section>

        {myPicks && <MyPicksPanel picks={myPicks} />}
      </div>

      {/* HumanVerificationOverlay (mounted around this whole page) owns
          the Turnstile widget container and the failure UI. */}

      <SubmitBar
        used={profile?.submission_count ?? 0}
        cap={event.submission_cap_per_guest}
        onOpenSearch={openSearch}
      />

      <EmailRecoveryModal
        open={recoveryOpen}
        onClose={() => setRecoveryOpen(false)}
        onRecovered={async () => {
          await refreshIdentity();
          // The polling loop (useEffect keyed on code/tab/gateComplete) re-uses
          // the updated cookie on its next tick (~5 s). No explicit refetch
          // needed — the merged guest_id propagates automatically via the
          // cookie on the next api.getCollectMyPicks() call.
        }}
      />

      {detailRow && (
        <CollectDetailSheet
          row={detailRow}
          code={code}
          rank={(leaderboard?.requests ?? []).findIndex((r) => r.id === detailRow.id) + 1 || 1}
          totalCount={leaderboard?.total ?? 0}
          voted={detailVoted || votedIds.has(detailRow.id)}
          voteError={detailVoteError}
          onVote={async () => {
            if (!detailVoted && !votedIds.has(detailRow.id)) {
              setDetailVoted(true);
              setDetailVoteError(null);
              try {
                await api.voteCollectRequest(code, detailRow.id, reverify);
              } catch {
                setDetailVoted(false);
                setDetailVoteError('Could not submit your vote. Please try again.');
              }
            }
          }}
          onClose={() => {
            setDetailRow(null);
            setDetailVoted(false);
            setDetailVoteError(null);
          }}
          reverify={reverify}
        />
      )}

      {search.searchOpen && (
        <CollectSearchSheet
          averageBpm={leaderboardAvgBpm}
          search={search}
          submission={{
            submitting: submission.submitting,
            submitError: submission.submitError,
            handleSelectSong: submission.handleSelectSong,
          }}
          onClose={closeSearch}
        />
      )}
    </main>
    </EmailGate>,
  );
}

function formatCountdown(target: Date | null): string {
  if (!target) return '';
  const diff = target.getTime() - Date.now();
  if (diff <= 0) return 'now';
  const hrs = Math.floor(diff / 3_600_000);
  const mins = Math.floor((diff % 3_600_000) / 60_000);
  const days = Math.floor(hrs / 24);
  if (days >= 1) return `${days}d ${hrs % 24}h`;
  return `${hrs}h ${mins}m`;
}
