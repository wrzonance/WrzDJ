'use client';

import { useParams, useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import {
  apiClient,
  ApiError,
  CollectEventPreview,
  CollectLeaderboardResponse,
  CollectLeaderboardRow,
  CollectMyPicksResponse,
  SearchResult,
} from '../../../lib/api';
import { useGuestIdentity } from '../../../lib/use-guest-identity';
import { useHumanVerification } from '@/lib/useHumanVerification';
import { IdentityBar } from '../../../components/IdentityBar';
import { NicknameGate, GateResult } from '../../../components/NicknameGate';
import EmailGate from '../../../components/EmailGate';
import EmailRecoveryButton from '../../../components/EmailRecoveryButton';
import EmailRecoveryModal from '../../../components/EmailRecoveryModal';
import HumanVerificationOverlay from '../../../components/HumanVerificationOverlay';
import CollectDetailSheet from './components/CollectDetailSheet';
import LeaderboardTabs from './components/LeaderboardTabs';
import MyPicksPanel from './components/MyPicksPanel';
import SubmitBar from './components/SubmitBar';

const POLL_MS = 5000;

export default function CollectPage() {
  const router = useRouter();
  const params = useParams<{ code: string }>();
  const code = params?.code ?? '';
  const { reconcileHint, refresh: refreshIdentity } = useGuestIdentity();
  const { state: humanState, reverify, retry, widgetContainerRef } = useHumanVerification();

  const [event, setEvent] = useState<CollectEventPreview | null>(null);
  const [leaderboard, setLeaderboard] = useState<CollectLeaderboardResponse | null>(null);
  const [myPicks, setMyPicks] = useState<CollectMyPicksResponse | null>(null);
  // Canonical "I have voted on this request" set — covers both upvotes AND
  // votes on my own submissions (which don't appear in `upvoted` because the
  // backend dedupes that against `submitted` for display purposes).
  const votedIds = new Set<number>([
    ...(myPicks?.voted_request_ids ?? []),
    ...(myPicks?.submitted ?? []).map((s) => s.id),
  ]);
  const [tab, setTab] = useState<'trending' | 'all'>('all');
  const [error, setError] = useState<string | null>(null);
  const [emailVerified, setEmailVerified] = useState(false);
  const [nickname, setNickname] = useState<string | null>(null);
  const [profile, setProfile] = useState<{
    submission_count: number;
    submission_cap: number;
  } | null>(null);

  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [gateComplete, setGateComplete] = useState(false);
  const handleGateComplete = (result: GateResult) => {
    setNickname(result.nickname || null);
    setEmailVerified(result.emailVerified);
    setProfile({ submission_count: result.submissionCount, submission_cap: result.submissionCap });
    setGateComplete(true);
  };

  const [detailRow, setDetailRow] = useState<CollectLeaderboardRow | null>(null);
  const [detailVoted, setDetailVoted] = useState(false);

  // Search modal state
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [sortByVibes, setSortByVibes] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [enrichedResults, setEnrichedResults] = useState<SearchResult[]>([]);

  const openSearch = () => {
    setSearchOpen(true);
    setSearchQuery('');
    setSearchResults([]);
    setSubmitError(null);
  };

  const closeSearch = () => {
    setSearchOpen(false);
    setSearchQuery('');
    setSearchResults([]);
    setSubmitError(null);
    setSortByVibes(false);
    setEnrichedResults([]);
    setEnriching(false);
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const results = await apiClient.eventSearch(code, searchQuery);
      setSearchResults(results);
    } catch {
      try {
        const results = await apiClient.search(searchQuery);
        setSearchResults(results);
      } catch {
        // silently leave results empty
      }
    } finally {
      setSearching(false);
    }
  };

  const handleSelectSong = async (song: SearchResult) => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const submitNickname = nickname ?? undefined;
      const result = await apiClient.submitCollectRequest(code, {
        song_title: song.title,
        artist: song.artist,
        source: song.source as 'spotify' | 'beatport' | 'tidal' | 'manual',
        source_url: song.url ?? undefined,
        artwork_url: song.album_art ?? undefined,
        nickname: submitNickname,
      }, reverify);

      if (result.is_duplicate) {
        setSubmitError('Great minds think alike! Your vote has been added.');
      }

      const [p, lb] = await Promise.all([
        apiClient.getCollectProfile(code),
        apiClient.getCollectLeaderboard(code, tab),
      ]);
      setProfile({ submission_count: p.submission_count, submission_cap: p.submission_cap });
      setLeaderboard(lb);

      if (!result.is_duplicate) {
        closeSearch();
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setSubmitError('Picks limit reached');
      } else if (err instanceof ApiError && err.status === 409) {
        setSubmitError('You already picked this one!');
      } else {
        setSubmitError('Failed to submit. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleVibesToggle = async () => {
    if (sortByVibes) {
      setSortByVibes(false);
      setEnrichedResults([]);
      return;
    }
    setSortByVibes(true);
    const needsEnrich = searchResults.slice(0, 10).filter((r) => r.bpm == null);
    if (needsEnrich.length === 0) return;
    setEnriching(true);
    try {
      const results = await apiClient.enrichPreview(
        code,
        searchResults.slice(0, 10).map((r) => ({
          title: r.title,
          artist: r.artist,
          source_url: r.url ?? undefined,
        })),
      );
      const merged = searchResults.map((r, i) => {
        const enriched = results[i];
        if (!enriched) return r;
        return {
          ...r,
          bpm: r.bpm ?? enriched.bpm ?? null,
          key: r.key ?? enriched.key ?? null,
          genre: r.genre ?? enriched.genre ?? null,
        };
      });
      setEnrichedResults(merged as SearchResult[]);
    } catch {
      // swallow — vibes still works with whatever bpm data is already on results
    } finally {
      setEnriching(false);
    }
  };

  useEffect(() => {
    if (!gateComplete) return;
    if (!code) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const ev = await apiClient.getCollectEvent(code);
        if (cancelled) return;
        setEvent(ev);
        if (ev.phase === 'live' || ev.phase === 'closed') {
          // Don't redirect to /join until we KNOW we're verified — the
          // join_code is gated. The overlay should already be holding the
          // UI if not verified; the timer below keeps polling so the next
          // tick retries the redirect once humanState flips.
          if (humanState === 'verified') {
            try {
              const { join_code } = await apiClient.getLiveJoinCode(code);
              if (cancelled) return;
              sessionStorage.setItem(`wrzdj_live_splash_${code}`, '1');
              router.replace(`/join/${join_code}`);
              return; // navigation issued; no need to reschedule
            } catch (err) {
              // 403 → cookie expired mid-session; trigger overlay re-verification
              // so the user isn't silently stuck on /collect after live-phase begins.
              // 409 (phase mismatch) or any other error → fall through to the
              // timer scheduling below so polling continues.
              if (err instanceof ApiError && err.status === 403) {
                void reverify();
              }
            }
          }
        } else if (ev.phase === 'collection') {
          // Leaderboard is ungated; my-picks requires email verification, so skip
          // it until the guest verifies to avoid surfacing a sticky 403 error.
          const lb = await apiClient.getCollectLeaderboard(code, tab);
          if (!cancelled) setLeaderboard(lb);
          if (emailVerified) {
            const picks = await apiClient.getCollectMyPicks(code);
            if (!cancelled) setMyPicks(picks);
          }
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
      if (!cancelled && document.visibilityState === 'visible') {
        timer = setTimeout(tick, POLL_MS);
      }
    };

    tick();
    const onVisibility = () => {
      if (document.visibilityState === 'visible' && !cancelled) tick();
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [code, tab, gateComplete, emailVerified, humanState, router]);

  const leaderboardAvgBpm = useMemo(() => {
    const withBpm = (leaderboard?.requests ?? []).filter((r) => r.bpm != null);
    return withBpm.length > 0
      ? withBpm.reduce((s, r) => s + (r.bpm ?? 0), 0) / withBpm.length
      : 128;
  }, [leaderboard]);

  const tierInfo: Record<string, { rail: string; label: string }> = {
    perfect: { rail: '#00f0ff', label: 'IN THE POCKET' },
    good:    { rail: '#ff2bd6', label: 'BLENDS WELL' },
    ok:      { rail: 'rgba(255,255,255,0.4)', label: 'SLIGHT SHIFT' },
    far:     { rail: 'rgba(255,255,255,0.2)', label: 'TEMPO JUMP' },
  };

  const vibeScored = useMemo(() => {
    const base = enrichedResults.length > 0 ? enrichedResults : searchResults;
    if (!base.length) return base;
    return base.map((r) => {
      const dBpm = Math.abs((r.bpm ?? leaderboardAvgBpm) - leaderboardAvgBpm);
      const score = dBpm / 8;
      const tier: 'perfect' | 'good' | 'ok' | 'far' =
        score <= 1 ? 'perfect' : score <= 2.5 ? 'good' : score <= 4 ? 'ok' : 'far';
      return { ...r, _score: score, _tier: tier };
    }).sort((a, b) => sortByVibes ? (a._score ?? 0) - (b._score ?? 0) : 0);
  }, [searchResults, enrichedResults, sortByVibes, leaderboardAvgBpm]);

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
                {(leaderboard?.requests ?? []).length}
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
            onTabChange={setTab}
            onVote={(id) => apiClient.voteCollectRequest(code, id, reverify)}
            votedIds={votedIds}
            onRowClick={setDetailRow}
          />
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
          // cookie on the next apiClient.getCollectMyPicks() call.
        }}
      />

      {detailRow && (
        <CollectDetailSheet
          row={detailRow}
          code={code}
          rank={(leaderboard?.requests ?? []).findIndex((r) => r.id === detailRow.id) + 1 || 1}
          totalCount={leaderboard?.requests.length ?? 0}
          voted={detailVoted || votedIds.has(detailRow.id)}
          onVote={async () => {
            if (!detailVoted && !votedIds.has(detailRow.id)) {
              setDetailVoted(true);
              try {
                await apiClient.voteCollectRequest(code, detailRow.id, reverify);
              } catch {
                setDetailVoted(false);
              }
            }
          }}
          onClose={() => { setDetailRow(null); setDetailVoted(false); }}
          reverify={reverify}
        />
      )}

      {searchOpen && (
        <div
          className="gst-request-sheet"
          onClick={closeSearch}
          role="dialog"
          aria-label="Request a song"
          style={{ background: '#0a0a12' }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
          >
            {/* Header */}
            <div style={{ padding: '12px 18px 10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'relative', zIndex: 1 }}>
              <div style={{ fontSize: 26.6, fontWeight: 800, letterSpacing: -0.5, color: '#fff' }}>Request a song</div>
              <button
                type="button"
                onClick={closeSearch}
                aria-label="Close search"
                style={{
                  width: 36, height: 36, borderRadius: 10,
                  background: surface, border: `1px solid ${border}`, color: '#fff',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 14 14">
                  <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                </svg>
              </button>
            </div>

            {submitError && <div className="collect-error" style={{ margin: '0 18px 8px' }}>{submitError}</div>}

            <div style={{ padding: '6px 18px 12px', position: 'relative', zIndex: 1 }}>
              <form onSubmit={handleSearch}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '12px 14px', borderRadius: 14,
                  background: surface, border: `1px solid ${border}`,
                  boxShadow: `inset 0 0 0 1px ${accent}30`,
                }}>
                  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, color: subFg }}>
                    <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5"/>
                    <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                  <input
                    type="text"
                    placeholder="Search for a song or artist…"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    required
                    autoFocus
                    data-testid="collect-search-input"
                    style={{
                      flex: 1, background: 'transparent', border: 'none',
                      color: '#fff', fontFamily: 'var(--font-grotesk, inherit)', fontSize: 18.2, fontWeight: 500,
                      outline: 'none',
                    }}
                  />
                </div>
                <button
                  type="submit"
                  style={{
                    width: '100%', marginTop: 8, height: 44, borderRadius: 10,
                    background: `linear-gradient(90deg, ${accent}, ${accent2})`,
                    border: 'none', color: '#000',
                    fontFamily: 'var(--font-grotesk, system-ui)', fontSize: 16.9, fontWeight: 800,
                    cursor: searching ? 'default' : 'pointer', opacity: searching ? 0.7 : 1,
                  }}
                  disabled={searching}
                >
                  {searching ? 'Searching…' : 'Search'}
                </button>
              </form>
            </div>

            {vibeScored.length > 0 && (
              <div style={{ flex: 1, overflowY: 'auto', padding: '0 18px 80px', position: 'relative', zIndex: 1 }}>
                {/* Results header with vibes toggle */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0 10px' }}>
                  <span style={{ fontSize: 10.9, fontFamily: 'var(--font-mono, monospace)', color: 'rgba(255,255,255,0.35)', letterSpacing: 1.5 }}>
                    {searchResults.length} RESULTS
                  </span>
                  <div style={{ flex: 1 }} />
                  <button
                    type="button"
                    onClick={handleVibesToggle}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 7,
                      padding: '6px 11px', borderRadius: 99,
                      background: sortByVibes ? 'rgba(0,240,255,0.12)' : 'transparent',
                      border: `1px solid ${sortByVibes ? accent : border}`,
                      color: sortByVibes ? accent : subFg,
                      fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, fontWeight: 700, letterSpacing: 1.2,
                      cursor: 'pointer',
                    }}
                  >
                    {enriching
                      ? <><span className="vbs-scan-icon">🔍</span> READING VIBES…</>
                      : <><span style={{
                          width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                          background: sortByVibes ? accent : 'transparent',
                          border: sortByVibes ? 'none' : `1px solid ${subFg}`,
                          boxShadow: sortByVibes ? `0 0 6px ${accent}` : 'none',
                          display: 'inline-block',
                        }} /> HIGHLIGHT BY VIBES</>
                    }
                  </button>
                </div>

                {/* Result rows */}
                {vibeScored.map((result, index) => {
                  const tier = sortByVibes ? (result as SearchResult & { _tier?: string })._tier : undefined;
                  const tc = tier ? tierInfo[tier] : null;

                  return (
                    <button
                      type="button"
                      key={result.spotify_id ?? result.url ?? index}
                      disabled={submitting}
                      onClick={() => handleSelectSong(result)}
                      data-testid="collect-search-result"
                      className={enriching ? 'vbs-scanning' : ''}
                      style={{
                        width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 0,
                        padding: 0, borderRadius: 12, marginBottom: 6,
                        background: surface, border: `1px solid ${border}`,
                        color: '#fff', cursor: 'pointer', overflow: 'hidden',
                      }}
                    >
                      {sortByVibes && !enriching && tc && (
                        <div style={{ width: 4, flexShrink: 0, background: tc.rail, alignSelf: 'stretch' }} />
                      )}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 12px', flex: 1, minWidth: 0 }}>
                        {result.album_art ? (
                          <img
                            src={result.album_art}
                            alt={result.album ?? result.title}
                            style={{ width: 44, height: 44, borderRadius: 8, objectFit: 'cover', flexShrink: 0 }}
                          />
                        ) : (
                          <div style={{
                            width: 44, height: 44, borderRadius: 8, flexShrink: 0,
                            background: 'linear-gradient(135deg, #ff006e, #8338ec)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: 13.3, fontWeight: 800, color: '#fff',
                          }}>
                            {`${result.title[0] ?? '?'}${result.artist[0] ?? ''}`.toUpperCase()}
                          </div>
                        )}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 16.9, fontWeight: 700, letterSpacing: -0.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {result.title}
                          </div>
                          <div style={{ fontSize: 14.5, color: 'rgba(255,255,255,0.5)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {result.artist}
                          </div>
                          {enriching ? (
                            <div className="vbs-analyzing" style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 9.7, color: 'rgba(0,240,255,0.6)', letterSpacing: 1, marginTop: 4 }}>
                              ANALYZING…
                            </div>
                          ) : sortByVibes && tc ? (
                            <div className="vbs-tier-in" style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 9.7, color: tc.rail, letterSpacing: 1.2, marginTop: 4, fontWeight: 700 }}>
                              {tc.label}
                            </div>
                          ) : null}
                        </div>
                        <div style={{
                          width: enriching ? 0 : 32, height: 32, borderRadius: '50%', flexShrink: 0,
                          background: `conic-gradient(rgba(0,240,255,0.8) ${result.popularity}%, rgba(255,255,255,0.1) ${result.popularity}%)`,
                          display: enriching ? 'none' : 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 9.7, fontFamily: 'var(--font-mono, monospace)', fontWeight: 700, color: 'rgba(255,255,255,0.5)',
                        }} title={`Popularity: ${result.popularity}%`}>
                          {result.popularity}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
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
