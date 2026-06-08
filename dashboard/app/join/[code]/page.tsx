'use client';

import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useParams } from 'next/navigation';
import { api, ApiError, PublicEvent, GuestNowPlaying, GuestRequestInfo, PUBLIC_PAGE_MAX, SearchResult } from '@/lib/api';
import { useEventStream } from '@/lib/use-event-stream';
import { useGuestIdentity } from '@/lib/use-guest-identity';
import { useHumanVerification } from '@/lib/useHumanVerification';
import { NicknameGate, GateResult } from '@/components/NicknameGate';
import EmailRecoveryButton from '@/components/EmailRecoveryButton';
import EmailRecoveryModal from '@/components/EmailRecoveryModal';
import { IdentityBar } from '@/components/IdentityBar';
import MyRequestsTracker from './components/MyRequestsTracker';
import CelebrationOverlay from './components/CelebrationOverlay';
import Toast from './components/Toast';
import TickNumber from './components/TickNumber';
import Sparks from './components/Sparks';
import SongDetailSheet from './components/SongDetailSheet';

const POLL_INTERVAL_MS = 10000;
const BACKOFF_INTERVAL_MS = 60000;
/* Request list is a growing window: "Load more" grows displayLimit and every
   poll/SSE refresh re-fetches [0, displayLimit) so live vote/status updates
   stay correct without client-side dedup. */
const PAGE_SIZE = 100;

const ACCENT = '#00f0ff';
const ACCENT2 = '#ff2bd6';

/* Deterministic gradient for songs without artwork */
const GRADIENTS = [
  'linear-gradient(135deg, #ff006e, #8338ec, #3a86ff)',
  'linear-gradient(135deg, #ffbe0b, #fb5607)',
  'linear-gradient(135deg, #06ffa5, #0077b6)',
  'linear-gradient(135deg, #ff6b9d, #c44569)',
  'linear-gradient(135deg, #f72585, #7209b7)',
  'linear-gradient(135deg, #4cc9f0, #4361ee)',
  'linear-gradient(135deg, #f15bb5, #fee440)',
  'linear-gradient(135deg, #2dc653, #25a244)',
  'linear-gradient(135deg, #ef476f, #ffd166)',
];
function artGradient(seed: string) {
  const code = (seed.charCodeAt(0) || 0) + (seed.charCodeAt(1) || 0);
  return GRADIENTS[code % GRADIENTS.length];
}

/* Harmonic key distance (Camelot wheel) */
function keyDistance(a: string, b: string): number {
  const numA = parseInt(a), numB = parseInt(b);
  const letA = a.slice(-1), letB = b.slice(-1);
  const numDiff = Math.min(Math.abs(numA - numB), 12 - Math.abs(numA - numB));
  return numDiff + (letA === letB ? 0 : 1);
}

type TabView = 'leaderboard' | 'recent' | 'mine';

export default function JoinEventPage() {
  const params = useParams();
  const code = params.code as string;

  const { reconcileHint, refresh: refreshIdentity, isLoading: identityLoading } = useGuestIdentity();
  const { state: humanState, reverify, widgetContainerRef } = useHumanVerification();
  const [recoveryOpen, setRecoveryOpen] = useState(false);

  const [event, setEvent] = useState<PublicEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ message: string; status: number } | null>(null);

  const [guestRequests, setGuestRequests] = useState<GuestRequestInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [displayLimit, setDisplayLimit] = useState(PAGE_SIZE);
  const [pollInterval, setPollInterval] = useState(POLL_INTERVAL_MS);
  const [nowPlaying, setNowPlaying] = useState<GuestNowPlaying | null>(null);

  /* Local vote deltas for optimistic UI */
  const [localVoteDeltas, setLocalVoteDeltas] = useState<Record<number, number>>({});
  const [votingId, setVotingId] = useState<number | null>(null);
  const [votedIds, setVotedIds] = useState<Set<number>>(new Set());
  const [sparkId, setSparkId] = useState<number | null>(null);

  /* Song detail overlay */
  const [songDetail, setSongDetail] = useState<GuestRequestInfo | null>(null);

  /* Tab */
  const [activeTab, setActiveTab] = useState<TabView>('leaderboard');

  /* Request sheet — open when user hasn't requested yet, or via CTA */
  const [showRequestSheet, setShowRequestSheet] = useState(false);

  /* Search / submission flow state (lives inside request sheet) */
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedSong, setSelectedSong] = useState<SearchResult | null>(null);
  const [note, setNote] = useState('');
  const [nickname, setNickname] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [submitIsDuplicate, setSubmitIsDuplicate] = useState(false);
  const [submitVoteCount, setSubmitVoteCount] = useState(0);
  const [sortByVibes, setSortByVibes] = useState(false);

  /* My Requests tracking */
  const [myRequestIds, setMyRequestIds] = useState<Set<number>>(new Set());
  const [myRequestsRefreshKey, setMyRequestsRefreshKey] = useState(0);

  /* Celebration / toast */
  const [celebrationSong, setCelebrationSong] = useState<{
    title: string; artist: string; artwork_url?: string | null;
  } | null>(null);
  const [toast, setToast] = useState<{
    message: string; type: 'success' | 'info' | 'warning';
  } | null>(null);

  /* Gate */
  const [gateComplete, setGateComplete] = useState(false);
  const [autoNamed, setAutoNamed] = useState(false);
  /* Whether the frictionless-vs-nickname decision has resolved. NicknameGate
     must not render (and fire onComplete) until we've confirmed the event is
     not frictionless — otherwise a frictionless event would briefly show the
     gate. */
  const [gateDecided, setGateDecided] = useState(false);
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
        const res = await api.ensureGuestName(code, reverify);
        if (!active) return;
        setNickname(res.nickname);
        setAutoNamed(res.auto_generated);
        setGateComplete(true);
      } catch {
        // On any failure, fall back to the normal NicknameGate flow.
        if (active) setGateDecided(true);
      }
    })();
    return () => { active = false; };
  }, [code, gateComplete, identityLoading, reverify]);

  /* Rename affordance for auto-named (frictionless) guests. */
  const handleRename = useCallback(async (newName: string) => {
    const res = await api.ensureGuestName(code, reverify, newName);
    setNickname(res.nickname);
    setAutoNamed(false);
  }, [code, reverify]);

  /* Pre-event collect phase */
  const [collectPhase, setCollectPhase] = useState<
    'pre_announce' | 'collection' | 'live' | 'closed' | null
  >(null);

  /* Email verified */
  const [emailVerified, setEmailVerified] = useState(false);

  /* Load event */
  const loadEvent = useCallback(async () => {
    try {
      const data = await api.getPublicEvent(code);
      setEvent(data);
      setCollectPhase(data.phase);
      setError(null);
      try {
        const { has_requested } = await api.checkHasRequested(code);
        if (!has_requested) setShowRequestSheet(true);
      } catch {
        setShowRequestSheet(true);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError({ message: err.message, status: err.status });
      } else {
        setError({ message: 'Event not found or has expired.', status: 0 });
      }
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => {
    if (!gateComplete) return;
    loadEvent();
  }, [loadEvent, gateComplete]);

  /* Load collect phase */
  useEffect(() => {
    if (!gateComplete || !code) return;
    let cancelled = false;
    api.getCollectProfile(code)
      .then((profile) => {
        if (!cancelled) setEmailVerified(profile.email_verified);
      })
      .catch(() => { /* email-verified is best-effort on the live page */ });
    return () => { cancelled = true; };
  }, [code, gateComplete]);

  /* Poll guest requests — start as soon as event is loaded */
  const loadRequests = useCallback(async () => {
    try {
      const data = await api.getPublicRequests(code, displayLimit);
      setGuestRequests(data.requests);
      setNowPlaying(data.now_playing);
      setTotal(data.total ?? data.requests.length);
      setPollInterval(POLL_INTERVAL_MS);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setPollInterval(BACKOFF_INTERVAL_MS);
      }
    }
  }, [code, displayLimit]);

  useEffect(() => {
    if (!event) return;
    loadRequests();
    const id = setInterval(loadRequests, pollInterval);
    return () => clearInterval(id);
  }, [event, loadRequests, pollInterval]);

  /* My request IDs ref for SSE handler */
  const myRequestIdsRef = useRef(myRequestIds);
  myRequestIdsRef.current = myRequestIds;
  const loadRequestsRef = useRef(loadRequests);
  loadRequestsRef.current = loadRequests;

  const handleMyRequestIdsLoaded = useCallback((ids: Set<number>) => {
    setMyRequestIds(ids);
  }, []);

  /* SSE */
  useEventStream(event ? code : null, {
    onRequestCreated: () => { loadRequestsRef.current(); },
    onRequestStatusChanged: (data) => {
      loadRequestsRef.current();
      if (myRequestIdsRef.current.has(data.request_id)) {
        const songName = data.title ?? 'Your song';
        switch (data.status) {
          case 'accepted':
            setToast({ message: `"${songName}" was accepted!`, type: 'success' });
            break;
          case 'playing':
            setToast({ message: `"${songName}" is playing now!`, type: 'success' });
            setCelebrationSong({ title: data.title ?? 'Your Song', artist: data.artist ?? '', artwork_url: null });
            break;
          case 'played':
            setToast({ message: `"${songName}" was played!`, type: 'info' });
            break;
          case 'rejected':
            setToast({ message: `"${songName}" was declined`, type: 'warning' });
            break;
        }
        setMyRequestsRefreshKey((k) => k + 1);
      }
    },
    onNowPlayingChanged: () => { loadRequestsRef.current(); },
    onRequestsBulkUpdate: () => { loadRequestsRef.current(); },
  });

  /* Sorted leaderboard with optimistic vote deltas */
  const leaderboardSorted = useMemo(() => {
    return [...guestRequests].sort((a, b) => {
      const va = a.vote_count + (localVoteDeltas[a.id] ?? 0);
      const vb = b.vote_count + (localVoteDeltas[b.id] ?? 0);
      return vb - va;
    });
  }, [guestRequests, localVoteDeltas]);

  const maxVotes = useMemo(() => {
    return Math.max(...leaderboardSorted.map(r => r.vote_count + (localVoteDeltas[r.id] ?? 0)), 1);
  }, [leaderboardSorted, localVoteDeltas]);

  /* Vote handler with optimistic update + spark detection */
  const handleVote = async (requestId: number) => {
    if (votedIds.has(requestId) || votingId !== null || myRequestIds.has(requestId)) return;

    const curVotes = (guestRequests.find(r => r.id === requestId)?.vote_count ?? 0) + (localVoteDeltas[requestId] ?? 0);

    /* Compute rank before + after for spark detection */
    const rankBefore = leaderboardSorted.findIndex(r => r.id === requestId);
    const afterDeltas = { ...localVoteDeltas, [requestId]: (localVoteDeltas[requestId] ?? 0) + 1 };
    const sortedAfter = [...guestRequests].sort((a, b) => {
      return (b.vote_count + (afterDeltas[b.id] ?? 0)) - (a.vote_count + (afterDeltas[a.id] ?? 0));
    });
    const rankAfter = sortedAfter.findIndex(r => r.id === requestId);
    if (rankAfter < 3 && rankBefore >= 3) setSparkId(requestId);

    setLocalVoteDeltas(afterDeltas);
    setVotingId(requestId);
    try {
      const result = await api.publicVoteRequest(requestId, reverify);
      setVotedIds((prev) => new Set([...prev, requestId]));
      setGuestRequests((prev) =>
        prev.map((r) => r.id === requestId ? { ...r, vote_count: result.vote_count } : r)
      );
      setLocalVoteDeltas((prev) => { const n = { ...prev }; delete n[requestId]; return n; });
    } catch (err) {
      setLocalVoteDeltas((prev) => { const n = { ...prev }; delete n[requestId]; return n; });
      if (err instanceof ApiError && err.status !== 429) {
        setVotedIds((prev) => new Set([...prev, requestId]));
      }
    } finally {
      setVotingId(null);
    }

    void curVotes; // suppress unused warning
  };

  /* Detail vote — delegates to handleVote */
  const handleDetailVote = async () => {
    if (!songDetail) return;
    const id = songDetail.id;
    if (votedIds.has(id) || myRequestIds.has(id)) return;
    await handleVote(id);
  };

  /* Search */
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const results = await api.eventSearch(code, searchQuery, reverify);
      setSearchResults(results);
    } catch {
      try {
        const results = await api.search(searchQuery);
        setSearchResults(results);
      } catch {
        // Both search paths failed; leave results empty and clear the spinner.
      }
    } finally {
      setSearching(false);
    }
  };

  /* Submit request */
  const handleSubmit = async () => {
    if (!selectedSong) return;
    setSubmitting(true);
    setSubmitError('');
    try {
      const result = await api.submitRequest(
        code,
        selectedSong.artist,
        selectedSong.title,
        note || undefined,
        selectedSong.url || undefined,
        selectedSong.album_art || undefined,
        searchQuery || undefined,
        { genre: selectedSong.genre ?? undefined, bpm: selectedSong.bpm ?? undefined, musical_key: selectedSong.key ?? undefined },
        selectedSong.source,
        nickname || undefined,
        reverify,
      );
      setMyRequestIds((prev) => new Set([...prev, result.id]));
      setMyRequestsRefreshKey((k) => k + 1);
      setSubmitted(true);
      setSubmitIsDuplicate(result.is_duplicate);
      setSubmitVoteCount(result.vote_count);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setEvent((prev) => prev ? { ...prev, requests_open: false } : prev);
        setSelectedSong(null);
        return;
      }
      setSubmitError('Failed to submit request. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const openRequestSheet = () => {
    setSearchQuery('');
    setSearchResults([]);
    setSelectedSong(null);
    setNote('');
    setSubmitted(false);
    setSubmitIsDuplicate(false);
    setSubmitVoteCount(0);
    setSubmitError('');
    setShowRequestSheet(true);
  };

  const closeRequestSheet = () => {
    setShowRequestSheet(false);
    setSelectedSong(null);
    setSearchQuery('');
    setSearchResults([]);
    setSubmitted(false);
    setSubmitError('');
  };

  /* "Queue Vibes" scoring for search results */
  const vibeScored = useMemo(() => {
    if (!searchResults.length) return searchResults;
    const withBpm = searchResults.filter(r => r.bpm != null);
    const avgBpm = withBpm.length
      ? withBpm.reduce((s, r) => s + (r.bpm ?? 0), 0) / withBpm.length
      : 120;
    return searchResults.map(r => {
      const dBpm = Math.abs((r.bpm ?? avgBpm) - avgBpm);
      const dKey = r.key ? keyDistance(r.key, nowPlaying ? '' : r.key) : 2;
      const score = (dBpm / 8) + dKey;
      const tier: 'perfect' | 'good' | 'ok' | 'far' =
        score <= 1 ? 'perfect' : score <= 2.5 ? 'good' : score <= 4 ? 'ok' : 'far';
      return { ...r, _score: score, _tier: tier };
    }).sort((a, b) => sortByVibes ? a._score - b._score : 0);
  }, [searchResults, sortByVibes, nowPlaying]);

  const tierInfo = {
    perfect: { rail: ACCENT, label: 'IN THE POCKET' },
    good: { rail: ACCENT2, label: 'BLENDS WELL' },
    ok: { rail: 'rgba(255,255,255,0.4)', label: 'SLIGHT SHIFT' },
    far: { rail: 'rgba(255,255,255,0.2)', label: 'KEY/TEMPO JUMP' },
  };

  /* ── Early returns ──────────────────────────────────────────── */

  if (!gateComplete) {
    // Wait for the frictionless decision before rendering the nickname gate,
    // so frictionless events never flash the gate on their way to auto-name.
    if (!gateDecided) {
      return (
        <div className="guest-tower" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 13.3, color: 'rgba(255,255,255,0.4)', letterSpacing: 2 }}>
            LOADING…
          </div>
        </div>
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
  const surfaceHi = 'rgba(255,255,255,0.06)';
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

  /* Rows for the active tab */
  const tabRows =
    activeTab === 'leaderboard'
      ? leaderboardSorted
      : activeTab === 'recent'
        ? guestRequests
        : guestRequests.filter(r => myRequestIds.has(r.id));

  /* ── Main Tower layout ───────────────────────────────────────── */
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

      {/* Hidden tracker for my-request IDs + SSE updates */}
      <div style={{ display: 'none' }}>
        <MyRequestsTracker
          eventCode={code}
          refreshKey={myRequestsRefreshKey}
          onRequestIdsLoaded={handleMyRequestIdsLoaded}
        />
      </div>

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

        {/* ── Tabs ─────────────────────────────────────────── */}
        <div className="gst-tabs" style={{ position: 'relative', zIndex: 1 }}>
          {(['leaderboard', 'recent', 'mine'] as TabView[]).map((t) => (
            <button
              key={t}
              className={`gst-tab${activeTab === t ? ' active' : ''}`}
              onClick={() => setActiveTab(t)}
              style={{
                color: activeTab === t ? '#06060a' : subFg,
                border: activeTab === t ? 'none' : `1px solid ${border}`,
              }}
            >
              {t === 'leaderboard' ? 'LEADERBOARD' : t === 'recent' ? 'RECENT' : 'MINE'}
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, color: subFg, letterSpacing: 1.2 }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: ACCENT, animation: 'gst-live-pulse 1.6s infinite' }} />
            LIVE
          </div>
        </div>

        {/* ── Request list / empty state ────────────────────── */}
        <div style={{ padding: '0 12px', position: 'relative', zIndex: 1 }}>
          {tabRows.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '2.5rem 0', color: subFg, fontSize: 16.9 }}>
              {activeTab === 'mine' ? 'No requests from you yet.' : 'No requests yet. Be the first!'}
            </div>
          ) : (
            tabRows.map((req, i) => {
              const effectiveVotes = req.vote_count + (localVoteDeltas[req.id] ?? 0);
              const pct = (effectiveVotes / maxVotes) * 100;
              const isTop3 = activeTab === 'leaderboard' && i < 3;
              const rankColors = [ACCENT, '#fff', subFg];
              const isMine = myRequestIds.has(req.id);
              const isVoted = votedIds.has(req.id) || isMine;

              return (
                <div
                  key={req.id}
                  className="gst-tower-row guest-request-item"
                  style={{
                    background: isMine ? `${ACCENT}14` : surface,
                    border: `1px solid ${isMine ? `${ACCENT}50` : border}`,
                  }}
                  onClick={() => setSongDetail(req)}
                >
                  {/* Vote bar fill */}
                  <div style={{
                    position: 'absolute', top: 0, left: 0, bottom: 0,
                    width: `${pct}%`,
                    background: `linear-gradient(90deg, ${isTop3 ? ACCENT : ACCENT2}1c, transparent 85%)`,
                    pointerEvents: 'none',
                    transition: 'width 360ms cubic-bezier(.2,.8,.2,1)',
                  }} />

                  {/* #1 top-edge glow */}
                  {i === 0 && activeTab === 'leaderboard' && (
                    <div style={{
                      position: 'absolute', left: 0, right: 0, top: 0, height: 1,
                      background: `linear-gradient(90deg, transparent, ${ACCENT}, transparent)`,
                    }} />
                  )}

                  <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 9, width: '100%' }}>
                    {/* Rank bubble */}
                    {activeTab === 'leaderboard' && (
                      <div style={{
                        width: 32, height: 32, flexShrink: 0, borderRadius: 8, position: 'relative',
                        background: isTop3 ? rankColors[i] : 'transparent',
                        border: isTop3 ? 'none' : `1px solid ${border}`,
                        color: isTop3 ? '#000' : subFg2,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontFamily: 'var(--font-mono, monospace)', fontSize: 14, fontWeight: 800,
                        boxShadow: i === 0 ? `0 0 14px ${ACCENT}50` : 'none',
                      }}>
                        {i + 1}
                        <Sparks accent={ACCENT} accent2={ACCENT2} fire={sparkId === req.id} onDone={() => setSparkId(null)} />
                      </div>
                    )}

                    {/* Artwork */}
                    <div style={{
                      width: 46, height: 46, borderRadius: 8, flexShrink: 0,
                      background: artGradient(req.title + req.artist), overflow: 'hidden',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 12.1, fontWeight: 800, color: '#fff',
                    }}>
                      {req.artwork_url
                        ? <img src={req.artwork_url} alt={req.title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        : `${req.title[0] ?? '?'}${req.artist[0] ?? ''}`.toUpperCase()
                      }
                    </div>

                    {/* Info */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 16.4, fontWeight: 700, letterSpacing: -0.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>
                          {req.title}
                        </span>
                        {isMine && (
                          <span className="gst-tag" style={{ color: ACCENT, background: `${ACCENT}14`, border: `1px solid ${ACCENT}55` }}>YOU</span>
                        )}
                        {req.status === 'accepted' && (
                          <span className="gst-tag" style={{ color: '#a78bfa', background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.3)' }}>
                            Accepted
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 15.2, color: subFg, marginTop: 2, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {req.artist}
                      </div>
                      {req.nickname && (
                        <div style={{ fontSize: 12.1, color: subFg2, marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          Requested by {req.nickname}
                          {req.requester_verified && <span style={{ color: '#22c55e', marginLeft: 4 }}>✓</span>}
                        </div>
                      )}
                    </div>

                    {/* Vote count + button */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0, marginLeft: 'auto' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                        <TickNumber
                          value={effectiveVotes}
                          style={{
                            fontFamily: 'var(--font-mono, monospace)', fontSize: 18.2, fontWeight: 800,
                            lineHeight: '1', color: isTop3 ? rankColors[i] : '#fff',
                            fontVariantNumeric: 'tabular-nums',
                          }}
                        />
                        <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 9, color: subFg, letterSpacing: 1, marginTop: 2 }}>
                          VOTES
                        </span>
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleVote(req.id); }}
                        disabled={votingId === req.id || isMine}
                        style={{
                          width: 38, height: 38, borderRadius: 8,
                          background: isVoted ? ACCENT : 'transparent',
                          border: `1px solid ${isVoted ? ACCENT : border}`,
                          color: isVoted ? '#000' : '#fff',
                          cursor: isMine ? 'default' : 'pointer',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          transition: 'all 160ms',
                          boxShadow: isVoted ? `0 0 14px ${ACCENT}80` : 'none',
                          opacity: votingId === req.id ? 0.6 : 1,
                        }}
                        title={isMine ? 'This is your request' : undefined}
                      >
                        <svg width="11" height="7" viewBox="0 0 11 7" fill="none" aria-hidden="true">
                          <path d="M1 6L5.5 1L10 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                        <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', opacity: 0 }}>▲</span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })
          )}

          {activeTab !== 'mine' && guestRequests.length < Math.min(total, PUBLIC_PAGE_MAX) ? (
            <button
              type="button"
              onClick={() => setDisplayLimit((d) => Math.min(d + PAGE_SIZE, PUBLIC_PAGE_MAX))}
              style={{
                width: '100%', marginTop: 10, padding: '13px 16px', borderRadius: 10,
                background: surface, border: `1px solid ${border}`, color: '#fff',
                fontFamily: 'var(--font-mono, monospace)', fontSize: 11.5, fontWeight: 700,
                letterSpacing: 1.4, cursor: 'pointer',
              }}
            >
              LOAD MORE · {Math.max(Math.min(total, PUBLIC_PAGE_MAX) - guestRequests.length, 0)} MORE
            </button>
          ) : tabRows.length > 0 ? (
            <div style={{ textAlign: 'center', padding: '10px 0 0', fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, color: subFg2, letterSpacing: 1.5 }}>
              ◇ END OF QUEUE ◇
            </div>
          ) : null}
        </div>
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
        <RequestSheetInline
          submitted={submitted}
          submitIsDuplicate={submitIsDuplicate}
          submitVoteCount={submitVoteCount}
          selectedSong={selectedSong}
          setSelectedSong={setSelectedSong}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          searchResults={vibeScored}
          searching={searching}
          note={note}
          setNote={setNote}
          submitting={submitting}
          submitError={submitError}
          setSubmitError={setSubmitError}
          sortByVibes={sortByVibes}
          setSortByVibes={setSortByVibes}
          tierInfo={tierInfo}
          onSearch={handleSearch}
          onSubmit={handleSubmit}
          onClose={closeRequestSheet}
          accent={ACCENT}
          accent2={ACCENT2}
          surface={surface}
          surfaceHi={surfaceHi}
          border={border}
          subFg={subFg}
          subFg2={subFg2}
        />
      )}

      {/* ── Song detail overlay ──────────────────────────────────── */}
      {songDetail && (
        <SongDetailSheet
          track={songDetail}
          rank={leaderboardSorted.findIndex(r => r.id === songDetail.id) + 1 || 1}
          totalCount={guestRequests.length}
          votes={songDetail.vote_count + (localVoteDeltas[songDetail.id] ?? 0)}
          voted={votedIds.has(songDetail.id) || myRequestIds.has(songDetail.id)}
          onVote={handleDetailVote}
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

/* ── Sub-components ───────────────────────────────────────────── */

function BannerBg({ url }: { url: string }) {
  return (
    <div className="join-banner-bg">
      <img src={url} alt="" />
    </div>
  );
}

function StatPill({ label, value, accent, sub, border }: {
  label: string; value: string; accent: string; sub: string; border: string;
}) {
  return (
    <div style={{ padding: '5px 10px', borderRadius: 7, border: `1px solid ${border}`, display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 42 }}>
      <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 15.2, fontWeight: 800, lineHeight: '1', color: accent }}>
        {value}
      </span>
      <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 9, color: sub, letterSpacing: 1.2, marginTop: 2.5 }}>
        {label}
      </span>
    </div>
  );
}

/* Inline request sheet (avoids prop-drilling by living in same file) */
interface RequestSheetProps {
  submitted: boolean;
  submitIsDuplicate: boolean;
  submitVoteCount: number;
  selectedSong: SearchResult | null;
  setSelectedSong: (s: SearchResult | null) => void;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  searchResults: (SearchResult & { _score?: number; _tier?: string })[];
  searching: boolean;
  note: string;
  setNote: (n: string) => void;
  submitting: boolean;
  submitError: string;
  setSubmitError: (e: string) => void;
  sortByVibes: boolean;
  setSortByVibes: (v: boolean) => void;
  tierInfo: Record<string, { rail: string; label: string }>;
  onSearch: (e: React.FormEvent) => void;
  onSubmit: () => void;
  onClose: () => void;
  accent: string;
  accent2: string;
  surface: string;
  surfaceHi: string;
  border: string;
  subFg: string;
  subFg2: string;
}

function RequestSheetInline({
  submitted, submitIsDuplicate, submitVoteCount,
  selectedSong, setSelectedSong,
  searchQuery, setSearchQuery, searchResults, searching,
  note, setNote, submitting, submitError, setSubmitError,
  sortByVibes, setSortByVibes, tierInfo,
  onSearch, onSubmit, onClose,
  accent, accent2, surface, surfaceHi, border, subFg, subFg2,
}: RequestSheetProps) {
  void surfaceHi;

  return (
    <div className="gst-request-sheet">
      {/* Glow */}
      <div style={{
        position: 'absolute', top: 80, left: '50%', transform: 'translateX(-50%)',
        width: '100%', maxWidth: 420, height: 300,
        background: `radial-gradient(circle, ${accent}18, transparent 70%)`,
        filter: 'blur(40px)', pointerEvents: 'none',
      }} />

      {/* Header */}
      <div style={{ padding: '12px 18px 10px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', position: 'relative', zIndex: 1 }}>
        <div>
          {!submitted && (
            <div style={{ fontSize: 10.9, fontFamily: 'var(--font-mono, monospace)', color: subFg, letterSpacing: 1.5, marginBottom: 4 }}>
              {selectedSong ? 'STEP 02 OF 02' : 'STEP 01 OF 02'}
            </div>
          )}
          <div style={{ fontSize: 26.6, fontWeight: 800, letterSpacing: -0.5, color: '#fff' }}>
            {submitted
              ? ''
              : selectedSong
                ? 'Confirm Request'
                : 'Request a song'}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            width: 40, height: 40, borderRadius: 11, marginTop: 2,
            background: surface, border: `1px solid ${border}`, color: '#fff',
            cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}
          aria-label="Close"
        >
          <svg width="14" height="14" viewBox="0 0 14 14">
            <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
          </svg>
        </button>
      </div>

      {/* ── Step 1: Search ──────────────────────────────── */}
      {!selectedSong && !submitted && (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, position: 'relative', zIndex: 1, overflow: 'hidden' }}>
          <div style={{ padding: '6px 18px 12px' }}>
            <form onSubmit={onSearch}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '14px 16px', borderRadius: 14,
                background: surface, border: `1px solid ${border}`,
                boxShadow: `inset 0 0 0 1px ${accent}30, 0 0 0 4px ${accent}10`,
              }}>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, color: subFg }}>
                  <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5"/>
                  <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search for a song or artist..."
                  style={{
                    flex: 1, background: 'transparent', border: 'none',
                    color: '#fff', fontFamily: 'var(--font-grotesk, inherit)', fontSize: 19.4, fontWeight: 500,
                    outline: 'none',
                  }}
                />
                <button
                  type="submit"
                  style={{
                    background: `linear-gradient(90deg, ${accent}, ${accent2})`,
                    border: 'none', color: '#000', padding: '9px 16px', borderRadius: 8,
                    fontFamily: 'var(--font-grotesk, inherit)', fontSize: 15.7, fontWeight: 800, cursor: 'pointer',
                    flexShrink: 0,
                  }}
                  disabled={searching}
                >
                  {searching ? '…' : 'Search'}
                </button>
              </div>
            </form>
          </div>

          {submitError && (
            <div className="collect-error" style={{ margin: '0 18px 8px' }}>{submitError}</div>
          )}

          <div style={{ flex: 1, overflowY: 'auto', padding: '4px 18px 120px' }}>
            {searchResults.length > 0 && (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0 10px' }}>
                  <span style={{ fontSize: 10.9, fontFamily: 'var(--font-mono, monospace)', color: subFg2, letterSpacing: 1.5 }}>
                    {searchResults.length} RESULTS
                  </span>
                  <div style={{ flex: 1 }} />
                  <button
                    onClick={() => setSortByVibes(!sortByVibes)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 7,
                      padding: '6px 11px', borderRadius: 99,
                      background: sortByVibes ? `${accent}18` : 'transparent',
                      border: `1px solid ${sortByVibes ? accent : border}`,
                      color: sortByVibes ? accent : subFg,
                      fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, fontWeight: 700, letterSpacing: 1.2,
                      cursor: 'pointer',
                    }}
                  >
                    <span style={{
                      width: 6, height: 6, borderRadius: '50%',
                      background: sortByVibes ? accent : 'transparent',
                      border: sortByVibes ? 'none' : `1px solid ${subFg}`,
                      boxShadow: sortByVibes ? `0 0 6px ${accent}` : 'none',
                      flexShrink: 0,
                    }} />
                    HIGHLIGHT BY VIBES
                  </button>
                </div>

                {searchResults.map((result, index) => {
                  const tier = (result as SearchResult & { _tier?: string })._tier;
                  const tc = tier ? tierInfo[tier] : null;
                  const isBeatport = result.source === 'beatport';

                  return (
                    <button
                      key={result.spotify_id || result.url || index}
                      onClick={() => { setSelectedSong(result); setSubmitError(''); }}
                      style={{
                        width: '100%', textAlign: 'left', display: 'flex', alignItems: 'stretch', gap: 0,
                        padding: 0, borderRadius: 12, marginBottom: 6,
                        background: surface, border: `1px solid ${border}`,
                        color: '#fff', cursor: 'pointer', overflow: 'hidden',
                      }}
                    >
                      {sortByVibes && tc && (
                        <div style={{ width: 4, flexShrink: 0, background: tc.rail }} />
                      )}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 12px', flex: 1, minWidth: 0 }}>
                        {result.album_art ? (
                          <img
                            src={result.album_art}
                            alt={result.album || result.title}
                            style={{ width: 44, height: 44, borderRadius: 8, objectFit: 'cover', flexShrink: 0 }}
                          />
                        ) : (
                          <div style={{
                            width: 44, height: 44, borderRadius: 8, flexShrink: 0,
                            background: artGradient(result.title + result.artist),
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: 13.3, fontWeight: 800, color: '#fff',
                          }}>
                            {`${result.title[0] ?? '?'}${result.artist[0] ?? ''}`.toUpperCase()}
                          </div>
                        )}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 18.2, fontWeight: 700, letterSpacing: -0.25, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {result.title}
                          </div>
                          <div style={{ fontSize: 15.7, color: subFg, marginTop: 2, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {result.artist}
                          </div>
                          {sortByVibes && tc && (
                            <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 10.3, color: tc.rail, letterSpacing: 1.2, marginTop: 4, fontWeight: 700 }}>
                              {tc.label}
                            </div>
                          )}
                        </div>
                        {isBeatport ? (
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, width: 32, height: 32 }} title="Beatport">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="#01ff28">
                              <circle cx="12" cy="12" r="10" fill="none" stroke="#01ff28" strokeWidth="2" />
                              <text x="12" y="16" textAnchor="middle" fontSize="11" fill="#01ff28" fontWeight="bold">B</text>
                            </svg>
                          </div>
                        ) : (
                          <div style={{
                            width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
                            background: `conic-gradient(${accent} ${result.popularity}%, rgba(255,255,255,0.1) ${result.popularity}%)`,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: 9.7, fontFamily: 'var(--font-mono, monospace)', fontWeight: 700, color: subFg,
                          }} title={`Popularity: ${result.popularity}%`}>
                            {result.popularity}
                          </div>
                        )}
                      </div>
                    </button>
                  );
                })}
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Step 2: Confirm / note ──────────────────────────── */}
      {selectedSong && !submitted && (
        <div style={{ flex: 1, padding: '4px 18px 18px', display: 'flex', flexDirection: 'column', position: 'relative', zIndex: 1 }}>
          {/* Selected song card */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12, padding: 12, borderRadius: 14,
            background: surface, border: `1px solid ${accent}55`,
            boxShadow: `0 0 0 4px ${accent}10`,
          }}>
            {selectedSong.album_art ? (
              <img
                src={selectedSong.album_art}
                alt={selectedSong.album || selectedSong.title}
                style={{ width: 56, height: 56, borderRadius: 10, objectFit: 'cover', flexShrink: 0 }}
              />
            ) : (
              <div style={{
                width: 56, height: 56, borderRadius: 10, flexShrink: 0,
                background: artGradient(selectedSong.title + selectedSong.artist),
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 15.7, fontWeight: 800, color: '#fff',
              }}>
                {`${selectedSong.title[0] ?? '?'}${selectedSong.artist[0] ?? ''}`.toUpperCase()}
              </div>
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 20.6, fontWeight: 700, letterSpacing: -0.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {selectedSong.title}
              </div>
              <div style={{ fontSize: 16.9, color: subFg, marginTop: 2, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {selectedSong.artist}
              </div>
              {selectedSong.album && (
                <div style={{ fontSize: 14.5, color: subFg2, marginTop: 1 }}>{selectedSong.album}</div>
              )}
            </div>
            <button
              onClick={() => setSelectedSong(null)}
              style={{ width: 28, height: 28, borderRadius: 7, background: 'transparent', border: `1px solid ${border}`, color: subFg, cursor: 'pointer', fontFamily: 'var(--font-mono, monospace)', fontSize: 15.7, flexShrink: 0 }}
            >
              ×
            </button>
          </div>

          {/* Note */}
          <div style={{ marginTop: 18 }}>
            <div style={{ fontSize: 12.1, fontFamily: 'var(--font-mono, monospace)', color: subFg, letterSpacing: 1.5, marginBottom: 8 }}>
              NOTE FOR THE DJ · OPTIONAL
            </div>
            <input
              id="note"
              type="text"
              className="input"
              placeholder="e.g., It's my birthday!"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={500}
              style={{ background: surface, border: `1px solid ${border}`, color: '#fff', borderRadius: 12, fontSize: 16.9 }}
            />
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
              {['🎂 birthday', '🌹 dedication', '🔥 dancefloor please', '💍 our song'].map(s => (
                <button
                  key={s}
                  onClick={() => setNote(s.replace(/^\S+\s/, ''))}
                  style={{
                    padding: '7px 11px', borderRadius: 99,
                    background: 'transparent', border: `1px solid ${border}`, color: subFg,
                    fontFamily: 'var(--font-grotesk, inherit)', fontSize: 14.5, cursor: 'pointer',
                  }}
                >{s}</button>
              ))}
            </div>
          </div>

          {submitError && (
            <div style={{ color: '#ef4444', fontSize: 16.9, marginTop: 12 }}>{submitError}</div>
          )}

          <div style={{ flex: 1 }} />

          <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
            <button
              onClick={onSubmit}
              disabled={submitting}
              style={{
                flex: 1, height: 54, borderRadius: 14,
                background: `linear-gradient(90deg, ${accent}, ${accent2})`,
                border: 'none', color: '#000',
                fontFamily: 'var(--font-grotesk, system-ui)', fontSize: 18.2, fontWeight: 800, letterSpacing: 0.3,
                cursor: submitting ? 'default' : 'pointer',
                boxShadow: `0 14px 36px -8px ${accent}90`,
                opacity: submitting ? 0.7 : 1,
              }}
            >
              {submitting ? 'Submitting...' : 'Submit Request'}
            </button>
            <button
              onClick={() => setSelectedSong(null)}
              style={{
                width: 88, height: 62, borderRadius: 14,
                background: surface, border: `1px solid ${border}`, color: '#fff',
                fontFamily: 'var(--font-grotesk, system-ui)', fontSize: 18.2, fontWeight: 700, cursor: 'pointer',
              }}
            >
              Back
            </button>
          </div>
        </div>
      )}

      {/* ── Success state ────────────────────────────────── */}
      {submitted && (
        <div style={{ flex: 1, padding: 18, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', position: 'relative', zIndex: 1 }}>
          <div style={{
            width: 96, height: 96, borderRadius: '50%',
            background: `radial-gradient(circle, ${accent}, ${accent2})`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: `0 0 60px ${accent}80, 0 0 120px ${accent2}40`,
            marginBottom: 20,
          }}>
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
              <path d="M10 20l7 7 13-15" stroke="#000" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <div style={{ fontSize: 26.6, fontWeight: 800, letterSpacing: -0.5 }}>
            {submitIsDuplicate ? 'Vote Added!' : 'Request Submitted!'}
          </div>
          {selectedSong && (
            <div style={{ fontSize: 16.9, color: subFg, marginTop: 6, maxWidth: 280 }}>
              {submitIsDuplicate
                ? `Someone already requested this song. Your vote has been added! ${submitVoteCount} ${submitVoteCount === 1 ? 'person wants' : 'people want'} this song.`
                : `"${selectedSong.title}" is queued. The DJ will see it soon.`}
            </div>
          )}
          <button
            onClick={onClose}
            style={{
              marginTop: 28, padding: '16px 36px', borderRadius: 12,
              background: 'transparent', color: '#fff', border: `1px solid ${border}`,
              fontFamily: 'var(--font-mono, monospace)', fontSize: 13.3, fontWeight: 700, letterSpacing: 1.5,
              cursor: 'pointer',
            }}
          >
            BACK TO QUEUE
          </button>
        </div>
      )}
    </div>
  );
}
