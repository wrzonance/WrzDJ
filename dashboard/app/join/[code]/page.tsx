'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { api, HumanVerificationRequiredError, GuestRequestInfo, PUBLIC_PAGE_MAX } from '@/lib/api';
import { useGuestIdentity } from '@/lib/use-guest-identity';
import { useHumanVerification, HumanVerificationFailedError } from '@/lib/use-human-verification';
import HumanVerificationOverlay from '@/components/HumanVerificationOverlay';
import { NicknameGate, GateResult } from '@/components/NicknameGate';
import EmailRecoveryButton from '@/components/EmailRecoveryButton';
import EmailRecoveryModal from '@/components/EmailRecoveryModal';
import { IdentityBar } from '@/components/IdentityBar';
import MyRequestsTracker from './components/MyRequestsTracker';
import CelebrationOverlay from './components/CelebrationOverlay';
import Toast from './components/Toast';
import SongDetailSheet from './components/SongDetailSheet';
import GuestRequestSheet from './components/GuestRequestSheet';
import RequestFeed from './components/RequestFeed';
import { artGradient, BannerBg, StatPill } from './components/JoinVisuals';
import { PAGE_SIZE, ACCENT, ACCENT2 } from './join-constants';
import { useGuestRequestVoting } from './useGuestRequestVoting';
import { useGuestEventData } from './useGuestEventData';

export default function JoinEventPage() {
  const params = useParams();
  const code = params.code as string;

  const { reconcileHint, refresh: refreshIdentity, isLoading: identityLoading } = useGuestIdentity();
  const { state: humanState, reverify, retry, widgetContainerRef } = useHumanVerification();
  const [recoveryOpen, setRecoveryOpen] = useState(false);

  const [nickname, setNickname] = useState('');
  /* Gate */
  const [gateComplete, setGateComplete] = useState(false);
  const [autoNamed, setAutoNamed] = useState(false);
  /* Whether the frictionless-vs-nickname decision has resolved. NicknameGate
     must not render (and fire onComplete) until we've confirmed the event is
     not frictionless — otherwise a frictionless event would briefly show the
     gate. */
  const [gateDecided, setGateDecided] = useState(false);
  /* Verification-blocked gate: ensure-name failed because the bot check is
     pending/failed (HumanVerificationRequiredError / HumanVerificationFailedError).
     This is NOT "frictionless unavailable" — we hold the guest on the
     verification overlay instead of degrading to NicknameGate (issue #419). */
  const [gateVerificationFailed, setGateVerificationFailed] = useState(false);
  const [gateAttempt, setGateAttempt] = useState(0);

  /* Song detail overlay */
  const [songDetail, setSongDetail] = useState<GuestRequestInfo | null>(null);

  /* Request sheet — open when user hasn't requested yet, or via CTA */
  const [showRequestSheet, setShowRequestSheet] = useState(false);

  /* My Requests tracking */
  const [myRequestIds, setMyRequestIds] = useState<Set<number>>(new Set());
  const [myRequestsRefreshKey, setMyRequestsRefreshKey] = useState(0);
  const [celebrationSong, setCelebrationSong] = useState<{
    title: string; artist: string; artwork_url?: string | null;
  } | null>(null);
  const [toast, setToast] = useState<{
    message: string; type: 'success' | 'info' | 'warning';
  } | null>(null);
  const eventData = useGuestEventData({
    code,
    enabled: gateComplete,
    myRequestIds,
    onMyRequestStatusChanged: (update) => {
      const songName = update.title ?? 'Your song';
      switch (update.status) {
        case 'accepted':
          setToast({ message: `"${songName}" was accepted!`, type: 'success' });
          break;
        case 'playing':
          setToast({ message: `"${songName}" is playing now!`, type: 'success' });
          setCelebrationSong({ title: update.title ?? 'Your Song', artist: update.artist ?? '', artwork_url: null });
          break;
        case 'played':
          setToast({ message: `"${songName}" was played!`, type: 'info' });
          break;
        case 'rejected':
          setToast({ message: `"${songName}" was declined`, type: 'warning' });
          break;
      }
      setMyRequestsRefreshKey((key) => key + 1);
    },
  });
  const {
    event,
    setEvent,
    loading,
    error,
    guestRequests,
    setGuestRequests,
    total,
    setDisplayLimit,
    nowPlaying,
    emailVerified,
    setEmailVerified,
    requestSheetSuggested,
    loadRequests,
  } = eventData;
  const collectPhase = event?.phase ?? null;
  const {
    clearSpark,
    handleDetailVote,
    handleVote,
    leaderboardSorted,
    localVoteDeltas,
    maxVotes,
    retryVote,
    sparkId,
    votedIds,
    votingId,
    voteError,
  } = useGuestRequestVoting({ guestRequests, myRequestIds, setGuestRequests, reverify });

  const handleGateComplete = (result: GateResult) => {
    setNickname(result.nickname);
    setGateComplete(true);
  };

  /* Decide gate mode on load. Frictionless events skip NicknameGate entirely:
     the guest gets an auto-generated name and lands straight on search. */
  useEffect(() => {
    if (gateComplete || identityLoading) return;
    let active = true;
    (async () => {
      try {
        const cfg = await api.getJoinConfig(code);
        if (!active) return;
        if (!cfg.frictionless_join) {
          setGateDecided(true); // not frictionless -> NicknameGate renders
          return;
        }
        const res = await api.ensureGuestName(code, { reverify });
        if (!active) return;
        setNickname(res.nickname);
        setAutoNamed(res.auto_generated);
        setGateComplete(true);
      } catch (err) {
        if (!active) return;
        if (
          err instanceof HumanVerificationRequiredError ||
          err instanceof HumanVerificationFailedError
        ) {
          // Bot check pending/failed — keep the verification overlay up
          // rather than silently degrading to the nickname/email gate.
          setGateVerificationFailed(true);
          return;
        }
        // frictionless_disabled / network errors -> normal NicknameGate flow.
        setGateDecided(true);
      }
    })();
    return () => { active = false; };
  }, [code, gateComplete, identityLoading, reverify, gateAttempt]);

  /* Rename affordance for auto-named (frictionless) guests. */
  const handleRename = useCallback(async (newName: string) => {
    const res = await api.ensureGuestName(code, { nickname: newName, reverify });
    setNickname(res.nickname);
    setAutoNamed(false);
  }, [code, reverify]);

  /* Re-run both the Turnstile widget and the frictionless decision after a
     verification failure (wired to the overlay's "Try again" button). */
  const retryGateVerification = useCallback(() => {
    setGateVerificationFailed(false);
    retry();
    setGateAttempt((a) => a + 1);
  }, [retry]);

  useEffect(() => {
    if (requestSheetSuggested) setShowRequestSheet(true);
  }, [requestSheetSuggested]);

  const handleMyRequestIdsLoaded = useCallback((ids: Set<number>) => {
    setMyRequestIds(ids);
  }, []);

  const openRequestSheet = () => setShowRequestSheet(true);
  const closeRequestSheet = () => setShowRequestSheet(false);

  /* ── Early returns ──────────────────────────────────────────── */

  if (!gateComplete) {
    // Wait for the frictionless decision before rendering the nickname gate,
    // so frictionless events never flash the gate on their way to auto-name.
    // The overlay keeps Turnstile's challenge reachable (and failures
    // visible/retryable) while the decision is pending (issue #419).
    if (!gateDecided) {
      return (
        <HumanVerificationOverlay
          state={gateVerificationFailed ? 'failed' : humanState}
          widgetContainerRef={widgetContainerRef}
          onRetry={retryGateVerification}
        >
          <div className="guest-tower" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 13.3, color: 'rgba(255,255,255,0.4)', letterSpacing: 2 }}>
              LOADING…
            </div>
          </div>
        </HumanVerificationOverlay>
      );
    }
    return <NicknameGate code={code} onComplete={handleGateComplete} reverify={reverify} />;
  }

  if (loading) {
    return (
      <div className="guest-tower" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 13.3, color: 'rgba(255,255,255,0.4)', letterSpacing: 2 }}>
          LOADING…
        </div>
      </div>
    );
  }

  if (error || !event) {
    const is410 = error?.status === 410;
    const is404 = error?.status === 404;
    return (
      <div className="guest-tower" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem' }}>
        <div style={{ textAlign: 'center', maxWidth: 360 }}>
          <div style={{ fontSize: 33.9, fontWeight: 800, letterSpacing: -0.6, marginBottom: 10 }}>
            {is410 ? 'Event Expired' : is404 ? 'Event Not Found' : 'Oops!'}
          </div>
          <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: 18.2 }}>
            {is410
              ? 'This event has ended and is no longer accepting requests.'
              : is404
                ? 'This event does not exist.'
                : error?.message || 'Event not found or has expired.'}
          </div>
        </div>
      </div>
    );
  }

  /* Requests closed — shown only before user has requested (no leaderboard yet) */
  if (!event.requests_open && !myRequestIds.size && guestRequests.length === 0 && !showRequestSheet) {
    return (
      <div className="guest-tower">
        {event.banner_url && <BannerBg url={event.banner_url} />}
        {nickname && (
          <IdentityBar nickname={nickname} emailVerified={emailVerified} onVerified={() => setEmailVerified(true)} autoNamed={autoNamed} onRename={handleRename} forceDark />
        )}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100dvh', padding: '2rem' }}>
          <div style={{ textAlign: 'center', maxWidth: 360 }}>
            <div style={{ fontSize: 31.5, fontWeight: 800, letterSpacing: -0.5, marginBottom: 8 }}>
              {event.name}
            </div>
            <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: 18.2 }}>
              Requests are closed for this event
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ── Shared colours ──────────────────────────────────────────── */
  const surface = 'rgba(255,255,255,0.04)';
  const border = 'rgba(255,255,255,0.08)';
  const subFg = 'rgba(255,255,255,0.5)';
  const subFg2 = 'rgba(255,255,255,0.35)';

  const phaseBanner =
    collectPhase === 'pre_announce' || collectPhase === 'collection' ? (
      <div className="join-pre-event-banner">
        🎟️ Pre-event voting is open —{' '}
        <a href={`/collect/${event.collection_code}`}>go to the pre-event page →</a>
      </div>
    ) : null;

  /* ── Main Tower layout ───────────────────────────────────────── */
  const detailRequest = songDetail
    ? guestRequests.find((request) => request.id === songDetail.id) ?? songDetail
    : null;

  return (
    <div className="guest-tower">
      {/* Ambient corner glows */}
      <div className="gst-glow-top" style={{ background: `radial-gradient(circle, ${ACCENT2}28, transparent 70%)` }} />
      <div className="gst-glow-bottom" style={{ background: `radial-gradient(circle, ${ACCENT}28, transparent 70%)` }} />

      {/* CelebrationOverlay + Toast */}
      <CelebrationOverlay song={celebrationSong} onClose={() => setCelebrationSong(null)} />
      {toast && <Toast message={toast.message} type={toast.type} onDismiss={() => setToast(null)} />}

      {/* Banner background */}
      {event.banner_url && <BannerBg url={event.banner_url} />}

      {/* Identity bar */}
      {nickname && (
        <IdentityBar nickname={nickname} emailVerified={emailVerified} onVerified={() => setEmailVerified(true)} autoNamed={autoNamed} onRename={handleRename} forceDark />
      )}

      <div className="guest-tower-inner">
        {/* Pre-event banner */}
        {phaseBanner}

        {/* ── Top bar ──────────────────────────────────────── */}
        <div style={{ padding: '10px 16px 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'relative', zIndex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <div style={{
              width: 34, height: 34, borderRadius: 8, flexShrink: 0,
              background: `conic-gradient(from 180deg, ${ACCENT}, ${ACCENT2}, ${ACCENT})`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 15.7, fontWeight: 800, color: '#000',
              boxShadow: `0 0 16px ${ACCENT}40`,
            }}>W</div>
            <div>
              <div style={{ fontSize: 16.9, fontWeight: 700, letterSpacing: -0.3, lineHeight: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '55vw' }}>
                {event.name}
              </div>
              <div style={{ fontSize: 10.9, fontFamily: 'var(--font-mono, monospace)', color: subFg, letterSpacing: 1.2, marginTop: 2 }}>
                {code.toUpperCase()}
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 5 }}>
            <StatPill label="QUEUE" value={String(total || guestRequests.length)} accent="#fff" sub={subFg} border={border} />
          </div>
        </div>

        {/* ── Recovery hint ─────────────────────────────────── */}
        <div style={{ padding: '0 16px 6px', position: 'relative', zIndex: 1 }}>
          <EmailRecoveryButton
            reconcileHint={reconcileHint}
            emailVerified={emailVerified}
            onOpen={() => setRecoveryOpen(true)}
          />
        </div>

        <div style={{ padding: '0 12px 8px', position: 'relative', zIndex: 1 }}>
          <MyRequestsTracker
            eventCode={code}
            refreshKey={myRequestsRefreshKey}
            onRequestIdsLoaded={handleMyRequestIdsLoaded}
          />
        </div>

        {/* ── Now Playing strip ─────────────────────────────── */}
        {nowPlaying && (
          <div className="gst-now-playing" style={{ background: surface, border: `1px solid ${border}`, position: 'relative', zIndex: 1 }}>
            <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: ACCENT, boxShadow: `0 0 14px ${ACCENT}`, borderRadius: '14px 0 0 14px' }} />
            <div style={{ width: 62, height: 62, borderRadius: 10, flexShrink: 0, overflow: 'hidden', position: 'relative' }}>
              {nowPlaying.album_art_url ? (
                <img src={nowPlaying.album_art_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              ) : (
                <div style={{ width: '100%', height: '100%', background: artGradient(nowPlaying.title), display: 'flex', alignItems: 'flex-end', padding: 5, gap: 2.5 }}>
                  {[0,1,2,3,4].map(i => (
                    <div key={i} style={{
                      flex: 1, background: 'rgba(255,255,255,0.9)', borderRadius: 1.5,
                      animation: `gst-eq-bar ${0.7 + i * 0.13}s ${i * 0.1}s infinite alternate ease-in-out`,
                      height: '40%', transformOrigin: 'bottom',
                    }} />
                  ))}
                </div>
              )}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 10.3, fontFamily: 'var(--font-mono, monospace)', fontWeight: 700, color: ACCENT, letterSpacing: 1.6 }}>
                  Now Playing
                </span>
              </div>
              <div style={{ fontSize: 17.6, fontWeight: 700, letterSpacing: -0.25, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {nowPlaying.title}
              </div>
              <div style={{ fontSize: 14, color: subFg, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {nowPlaying.artist}
              </div>
            </div>
          </div>
        )}

        <RequestFeed
          guestRequests={guestRequests}
          leaderboardSorted={leaderboardSorted}
          myRequestIds={myRequestIds}
          total={total}
          voting={{
            localVoteDeltas,
            maxVotes,
            sparkId,
            votedIds,
            votingId,
            voteError,
            clearSpark,
            handleVote,
            retryVote,
          }}
          onLoadMore={() => setDisplayLimit((limit) => Math.min(limit + PAGE_SIZE, PUBLIC_PAGE_MAX))}
          onSelectRequest={setSongDetail}
        />
      </div>

      {/* ── Human verification widget ────────────────────────────── */}
      <div
        ref={widgetContainerRef}
        style={{
          display: humanState === 'challenge' ? 'block' : 'none',
          margin: '1rem 0',
        }}
      />
      {humanState === 'failed' && (
        <div style={{ color: '#ef4444', marginTop: '0.5rem', fontSize: '0.9rem', textAlign: 'center' }}>
          Verification failed. Please refresh the page.
        </div>
      )}

      {/* ── Bottom CTA ───────────────────────────────────────────── */}
      <div className="gst-cta-wrap">
        {event.requests_open ? (
          <button
            onClick={openRequestSheet}
            style={{
              width: '100%', maxWidth: 500, margin: '0 auto', height: 62, borderRadius: 14,
              background: `linear-gradient(90deg, ${ACCENT}, ${ACCENT2})`,
              border: 'none', color: '#000',
              fontFamily: 'var(--font-grotesk, system-ui)', fontSize: 18.2, fontWeight: 800, letterSpacing: 0.4,
              cursor: 'pointer',
              boxShadow: `0 12px 32px -8px ${ACCENT}90, 0 0 0 1px rgba(255,255,255,0.15) inset`,
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9,
            }}
            aria-label="Request a song"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M7 1.5v11M1.5 7h11" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/>
            </svg>
            REQUEST A SONG
          </button>
        ) : (
          <div style={{ textAlign: 'center', color: subFg, padding: '0.75rem', fontFamily: 'var(--font-mono, monospace)', fontSize: 13.3, letterSpacing: 1 }}>
            Requests are closed for this event
          </div>
        )}
      </div>

      {/* ── Request sheet overlay ────────────────────────────────── */}
      {showRequestSheet && (
        <GuestRequestSheet
          code={code}
          nickname={nickname}
          nowPlaying={nowPlaying}
          setEvent={setEvent}
          reverify={reverify}
          onClose={closeRequestSheet}
          onSubmitted={(requestId) => {
            setMyRequestIds((prev) => new Set([...prev, requestId]));
            setMyRequestsRefreshKey((key) => key + 1);
          }}
          theme={{ accent: ACCENT, accent2: ACCENT2, surface, border, subFg, subFg2 }}
        />
      )}

      {/* ── Song detail overlay ──────────────────────────────────── */}
      {detailRequest && (
        <SongDetailSheet
          track={detailRequest}
          rank={leaderboardSorted.findIndex(r => r.id === detailRequest.id) + 1 || 1}
          totalCount={guestRequests.length}
          votes={detailRequest.vote_count + (localVoteDeltas[detailRequest.id] ?? 0)}
          voted={votedIds.has(detailRequest.id) || myRequestIds.has(detailRequest.id)}
          canVote={!myRequestIds.has(detailRequest.id)}
          isVoting={votingId === detailRequest.id}
          onVote={() => handleDetailVote(detailRequest.id)}
          onClose={() => setSongDetail(null)}
        />
      )}

      {/* ── Email recovery modal ─────────────────────────────────── */}
      <EmailRecoveryModal
        open={recoveryOpen}
        onClose={() => setRecoveryOpen(false)}
        onRecovered={async () => {
          await refreshIdentity();
          // The polling loop (useEffect keyed on event/loadRequests/pollInterval)
          // re-uses the updated guest cookie on its next tick (~10 s). Calling
          // loadRequests() here triggers an immediate refetch so guest-scoped
          // data (MyRequestsTracker, vote state) reflects the merged identity
          // without waiting for the next poll cycle.
          await loadRequests();
        }}
      />
    </div>
  );
}
