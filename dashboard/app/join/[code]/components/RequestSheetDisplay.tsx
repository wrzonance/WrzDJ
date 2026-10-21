'use client';

import type { SearchResult } from '@/lib/api';
import { artGradient } from '@/lib/art-gradient';
import SearchResultRow from '@/components/search/SearchResultRow';

interface RequestSearchState {
  selectedSong: SearchResult | null;
  setSelectedSong: (song: SearchResult | null) => void;
  query: string;
  setQuery: (query: string) => void;
  results: (SearchResult & { _score?: number; _tier?: string })[];
  searchError: string | null;
  searching: boolean;
  sortByVibes: boolean;
  setSortByVibes: (enabled: boolean) => void;
  tierInfo: Record<string, { rail: string; label: string }>;
  onSearch: (e: React.FormEvent) => void;
}

interface RequestSubmissionState {
  submitted: boolean;
  submitIsDuplicate: boolean;
  submitVoteCount: number;
  note: string;
  setNote: (n: string) => void;
  submitting: boolean;
  submitError: string;
  setSubmitError: (e: string) => void;
  onSubmit: () => void;
}

interface RequestSheetTheme {
  accent: string;
  accent2: string;
  surface: string;
  border: string;
  subFg: string;
  subFg2: string;
}

interface RequestSheetProps {
  search: RequestSearchState;
  submission: RequestSubmissionState;
  theme: RequestSheetTheme;
  onClose: () => void;
}

export function RequestSheetDisplay({ search, submission, theme, onClose }: RequestSheetProps) {
  const { selectedSong, setSelectedSong, query: searchQuery, setQuery: setSearchQuery, results: searchResults,
    searchError, searching, sortByVibes, setSortByVibes, tierInfo, onSearch } = search;
  const { submitted, submitIsDuplicate, submitVoteCount, note, setNote, submitting, submitError,
    setSubmitError, onSubmit } = submission;
  const { accent, accent2, surface, border, subFg, subFg2 } = theme;

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

          {searchError && (
            <div role="alert" className="collect-error" style={{ margin: '0 18px 8px' }}>
              {searchError}
            </div>
          )}

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
                    <SearchResultRow
                      key={result.spotify_id || result.url || index}
                      result={result}
                      appearance={{
                        surface, border, secondaryText: subFg,
                        title: { fontSize: 18.2, letterSpacing: -0.25 },
                        artist: { fontSize: 15.7, fontWeight: 500 }, vibe: { fontSize: 10.3 },
                        alignItems: 'stretch', artworkFallback: artGradient,
                      }}
                      vibe={sortByVibes && tc ? { railColor: tc.rail, label: tc.label, color: tc.rail } : undefined}
                      onSelect={(song) => { setSelectedSong(song); setSubmitError(''); }}
                      trailing={isBeatport ? (
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
                    />
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
