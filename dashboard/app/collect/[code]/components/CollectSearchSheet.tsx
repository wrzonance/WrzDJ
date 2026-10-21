'use client';

import { useMemo } from 'react';
import type { SearchResult } from '@/lib/api';
import SearchResultRow from '@/components/search/SearchResultRow';
import type { useCollectSearch } from '../useCollectSearch';
import type { useCollectSubmission } from '../useCollectSubmission';

type SearchState = Pick<
  ReturnType<typeof useCollectSearch>,
  | 'searchQuery'
  | 'setSearchQuery'
  | 'searchResults'
  | 'searchError'
  | 'searching'
  | 'sortByVibes'
  | 'enriching'
  | 'enrichedResults'
  | 'handleSearch'
  | 'handleVibesToggle'
>;

type SubmissionState = Pick<
  ReturnType<typeof useCollectSubmission>,
  'submitting' | 'submitError' | 'handleSelectSong'
>;

interface Props {
  averageBpm: number;
  search: SearchState;
  submission: SubmissionState;
  onClose: () => void;
}

type VibeTier = 'perfect' | 'good' | 'ok' | 'far';
type VibeScoredResult = SearchResult & { _score: number; _tier: VibeTier };

const ACCENT = '#00f0ff';
const ACCENT_TWO = '#ff2bd6';
const SURFACE = 'rgba(255,255,255,0.04)';
const BORDER = 'rgba(255,255,255,0.08)';
const SUBTLE_FOREGROUND = 'rgba(255,255,255,0.5)';
const VIBE_TIERS: Record<VibeTier, { rail: string; label: string }> = {
  perfect: { rail: '#00f0ff', label: 'IN THE POCKET' },
  good: { rail: '#ff2bd6', label: 'BLENDS WELL' },
  ok: { rail: 'rgba(255,255,255,0.4)', label: 'SLIGHT SHIFT' },
  far: { rail: 'rgba(255,255,255,0.2)', label: 'TEMPO JUMP' },
};

export default function CollectSearchSheet({ averageBpm, search, submission, onClose }: Props) {
  const vibeScored = useMemo<VibeScoredResult[]>(() => {
    const base = search.enrichedResults.length > 0 ? search.enrichedResults : search.searchResults;
    return base
      .map((result) => {
        const bpmDifference = Math.abs((result.bpm ?? averageBpm) - averageBpm);
        const score = bpmDifference / 8;
        const tier: VibeTier =
          score <= 1 ? 'perfect' : score <= 2.5 ? 'good' : score <= 4 ? 'ok' : 'far';
        return { ...result, _score: score, _tier: tier };
      })
      .sort((left, right) =>
        search.sortByVibes ? left._score - right._score : 0,
      );
  }, [search.searchResults, search.enrichedResults, search.sortByVibes, averageBpm]);

  return (
<div
          className="gst-request-sheet"
          onClick={onClose}
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
                onClick={onClose}
                aria-label="Close search"
                style={{
                  width: 36, height: 36, borderRadius: 10,
                  background: SURFACE, border: `1px solid ${BORDER}`, color: '#fff',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 14 14">
                  <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                </svg>
              </button>
            </div>

            {submission.submitError && <div className="collect-error" style={{ margin: '0 18px 8px' }}>{submission.submitError}</div>}

            <div style={{ padding: '6px 18px 12px', position: 'relative', zIndex: 1 }}>
              <form onSubmit={search.handleSearch}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '12px 14px', borderRadius: 14,
                  background: SURFACE, border: `1px solid ${BORDER}`,
                  boxShadow: `inset 0 0 0 1px ${ACCENT}30`,
                }}>
                  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0, color: SUBTLE_FOREGROUND }}>
                    <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5"/>
                    <path d="M11 11l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                  <input
                    type="text"
                    placeholder="Search for a song or artist…"
                    value={search.searchQuery}
                    onChange={(e) => search.setSearchQuery(e.target.value)}
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
                    background: `linear-gradient(90deg, ${ACCENT}, ${ACCENT_TWO})`,
                    border: 'none', color: '#000',
                    fontFamily: 'var(--font-grotesk, system-ui)', fontSize: 16.9, fontWeight: 800,
                    cursor: search.searching ? 'default' : 'pointer', opacity: search.searching ? 0.7 : 1,
                  }}
                  disabled={search.searching}
                >
                  {search.searching ? 'Searching…' : 'Search'}
                </button>
              </form>
            </div>

            {search.searchError && (
              <div role="alert" className="collect-error" style={{ margin: '0 18px 8px' }}>
                {search.searchError}
              </div>
            )}

            {vibeScored.length > 0 && (
              <div style={{ flex: 1, overflowY: 'auto', padding: '0 18px 80px', position: 'relative', zIndex: 1 }}>
                {/* Results header with vibes toggle */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0 10px' }}>
                  <span style={{ fontSize: 10.9, fontFamily: 'var(--font-mono, monospace)', color: 'rgba(255,255,255,0.35)', letterSpacing: 1.5 }}>
                    {search.searchResults.length} RESULTS
                  </span>
                  <div style={{ flex: 1 }} />
                  <button
                    type="button"
                    onClick={search.handleVibesToggle}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 7,
                      padding: '6px 11px', borderRadius: 99,
                      background: search.sortByVibes ? 'rgba(0,240,255,0.12)' : 'transparent',
                      border: `1px solid ${search.sortByVibes ? ACCENT : BORDER}`,
                      color: search.sortByVibes ? ACCENT : SUBTLE_FOREGROUND,
                      fontFamily: 'var(--font-mono, monospace)', fontSize: 10.9, fontWeight: 700, letterSpacing: 1.2,
                      cursor: 'pointer',
                    }}
                  >
                    {search.enriching
                      ? <><span className="vbs-scan-icon">🔍</span> READING VIBES…</>
                      : <><span style={{
                          width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                          background: search.sortByVibes ? ACCENT : 'transparent',
                          border: search.sortByVibes ? 'none' : `1px solid ${SUBTLE_FOREGROUND}`,
                          boxShadow: search.sortByVibes ? `0 0 6px ${ACCENT}` : 'none',
                          display: 'inline-block',
                        }} /> HIGHLIGHT BY VIBES</>
                    }
                  </button>
                </div>

                {/* Result rows */}
                {vibeScored.map((result, index) => {
                  const tier = search.sortByVibes ? result._tier : undefined;
                  const tc = tier ? VIBE_TIERS[tier] : null;

                  return (
                    <SearchResultRow
                      key={result.spotify_id ?? result.url ?? index}
                      result={result}
                      appearance={{
                        surface: SURFACE, border: BORDER, secondaryText: 'rgba(255,255,255,0.5)',
                        title: { fontSize: 16.9, letterSpacing: -0.2 },
                        artist: { fontSize: 14.5 }, vibe: { fontSize: 9.7 },
                        alignItems: 'center',
                        artworkFallback: () => 'linear-gradient(135deg, #ff006e, #8338ec)',
                      }}
                      onSelect={submission.handleSelectSong}
                      disabled={submission.submitting}
                      testId="collect-search-result"
                      className={search.enriching ? 'vbs-scanning' : ''}
                      vibe={search.enriching
                        ? { label: 'ANALYZING…', color: 'rgba(0,240,255,0.6)', className: 'vbs-analyzing', fontWeight: 400, letterSpacing: 1 }
                        : search.sortByVibes && tc
                          ? { railColor: tc.rail, label: tc.label, color: tc.rail, className: 'vbs-tier-in' }
                          : undefined}
                      trailing={(
                        <div style={{
                          width: search.enriching ? 0 : 32, height: 32, borderRadius: '50%', flexShrink: 0,
                          background: `conic-gradient(rgba(0,240,255,0.8) ${result.popularity}%, rgba(255,255,255,0.1) ${result.popularity}%)`,
                          display: search.enriching ? 'none' : 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 9.7, fontFamily: 'var(--font-mono, monospace)', fontWeight: 700, color: 'rgba(255,255,255,0.5)',
                        }} title={`Popularity: ${result.popularity}%`}>
                          {result.popularity}
                        </div>
                      )}
                    />
                  );
                })}
              </div>
            )}
          </div>
        </div>
  );
}
