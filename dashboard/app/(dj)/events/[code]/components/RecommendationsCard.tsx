'use client';

import { useState, useCallback, useRef, useMemo } from 'react';
import { api, ApiError } from '@/lib/api';
import { Tooltip } from '@/components/Tooltip';
import { KeyBadge, BpmBadge, GenreBadge } from '@/components/MusicBadges';
import { PreviewPlayer } from '@/components/PreviewPlayer';
import { computeBpmContext } from '@/lib/bpm-stats';
import { safeExternalUrl } from '@/lib/safe-url';
import type {
  RecommendedTrack,
  EventMusicProfile,
  RecommendationResponse,
  PlaylistInfo,
  LLMQueryInfo,
} from '@/lib/api-types';

type Mode = 'requests' | 'template' | 'llm';

interface ModeResultCache {
  suggestions: RecommendedTrack[];
  profile: EventMusicProfile | null;
  llmQueries: LLMQueryInfo[];
  llmModel: string;
  scrollTop: number;
}

const emptyCache: ModeResultCache = { suggestions: [], profile: null, llmQueries: [], llmModel: '', scrollTop: 0 };

interface RecommendationsCardProps {
  code: string;
  hasAcceptedRequests: boolean;
  tidalLinked: boolean;
  beatportLinked: boolean;
  onAcceptTrack: (track: RecommendedTrack) => Promise<void>;
}

export function RecommendationsCard({
  code,
  hasAcceptedRequests,
  tidalLinked,
  beatportLinked,
  onAcceptTrack,
}: RecommendationsCardProps) {
  const hasConnectedServices = tidalLinked || beatportLinked;

  const [suggestions, setSuggestions] = useState<RecommendedTrack[]>([]);
  const [profile, setProfile] = useState<EventMusicProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acceptingId, setAcceptingId] = useState<string | null>(null);
  const [acceptingAll, setAcceptingAll] = useState(false);

  // Template playlist state
  const [mode, setMode] = useState<Mode>('requests');
  const [playlists, setPlaylists] = useState<PlaylistInfo[]>([]);
  const [selectedPlaylist, setSelectedPlaylist] = useState<string | null>(null);
  const [loadingPlaylists, setLoadingPlaylists] = useState(false);
  const [playlistsLoaded, setPlaylistsLoaded] = useState(false);

  // Generate button state: 'idle' | 'working' | 'complete'
  const [generateState, setGenerateState] = useState<'idle' | 'working' | 'complete'>('idle');
  const completeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // LLM state
  const [llmAvailable, setLlmAvailable] = useState(false);
  const [llmPrompt, setLlmPrompt] = useState('');
  const [llmQueries, setLlmQueries] = useState<LLMQueryInfo[]>([]);
  const [showReasoning, setShowReasoning] = useState(false);
  const [llmModel, setLlmModel] = useState('');

  // Ref for the suggestions list container (scroll position save/restore)
  const suggestionsContainerRef = useRef<HTMLDivElement>(null);

  // Lock container height during mode switches to prevent page-level scroll jumps
  const [lockedHeight, setLockedHeight] = useState<number | null>(null);

  // BPM context from suggestion tracks — outlier-aware average for badge coloring
  const suggestionBpmContext = useMemo(() => {
    const bpms = suggestions
      .map((s) => s.bpm)
      .filter((b): b is number => b != null);
    return computeBpmContext(bpms);
  }, [suggestions]);

  // Per-mode results cache — persists suggestions across mode switches
  const resultsCacheRef = useRef<Record<Mode, ModeResultCache>>({
    requests: { ...emptyCache },
    template: { ...emptyCache },
    llm: { ...emptyCache },
  });

  const loadPlaylists = useCallback(async () => {
    if (playlistsLoaded) return;
    setLoadingPlaylists(true);
    try {
      const result = await api.getEventPlaylists(code);
      setPlaylists(result.playlists);
      setPlaylistsLoaded(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load playlists');
    } finally {
      setLoadingPlaylists(false);
    }
  }, [code, playlistsLoaded]);

  const handleModeChange = (newMode: Mode) => {
    if (newMode === mode) return;

    // Lock container height to prevent page-level scroll jump
    if (suggestionsContainerRef.current) {
      setLockedHeight(suggestionsContainerRef.current.offsetHeight);
    }

    // Save current mode's results and scroll position to cache
    resultsCacheRef.current[mode] = {
      suggestions,
      profile,
      llmQueries,
      llmModel,
      scrollTop: suggestionsContainerRef.current?.scrollTop ?? 0,
    };

    // Restore cached results for the new mode
    const cached = resultsCacheRef.current[newMode];
    setSuggestions(cached.suggestions);
    setProfile(cached.profile);
    setLlmQueries(cached.llmQueries);
    setLlmModel(cached.llmModel);

    // Restore scroll position after DOM update
    const savedScrollTop = cached.scrollTop;
    requestAnimationFrame(() => {
      if (suggestionsContainerRef.current) {
        suggestionsContainerRef.current.scrollTop = savedScrollTop;
      }
    });

    setMode(newMode);
    setError(null);
    setShowReasoning(false);
    setGenerateState('idle');
    if (completeTimerRef.current) {
      clearTimeout(completeTimerRef.current);
      completeTimerRef.current = null;
    }
    if (newMode === 'template') {
      loadPlaylists();
    }
  };

  const handleGenerate = async () => {
    if (completeTimerRef.current) {
      clearTimeout(completeTimerRef.current);
      completeTimerRef.current = null;
    }
    setLoading(true);
    setGenerateState('working');
    setError(null);
    setLlmQueries([]);
    try {
      if (mode === 'llm') {
        const result = await api.generateLLMRecommendations(code, llmPrompt);
        setSuggestions(result.suggestions);
        setProfile(result.profile);
        setLlmQueries(result.llm_queries);
        setLlmModel(result.llm_model);
      } else {
        let result: RecommendationResponse;
        if (mode === 'template' && selectedPlaylist) {
          const [source, playlistId] = selectedPlaylist.split(':');
          result = await api.generateRecommendationsFromTemplate(code, source, playlistId);
        } else {
          result = await api.generateRecommendations(code);
        }
        setSuggestions(result.suggestions);
        setProfile(result.profile);
        setLlmAvailable(result.llm_available);
      }
      setLockedHeight(null);
      setGenerateState('complete');
      completeTimerRef.current = setTimeout(() => setGenerateState('idle'), 2000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to generate suggestions');
      setGenerateState('idle');
    } finally {
      setLoading(false);
    }
  };

  const handleAccept = async (track: RecommendedTrack) => {
    const trackKey = `${track.artist}-${track.title}`;
    setAcceptingId(trackKey);
    try {
      await onAcceptTrack(track);
      setSuggestions((prev) => prev.filter((s) => `${s.artist}-${s.title}` !== trackKey));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to accept track');
    } finally {
      setAcceptingId(null);
    }
  };

  const handleAcceptAll = async () => {
    setAcceptingAll(true);
    try {
      for (const track of suggestions) {
        await onAcceptTrack(track);
      }
      setSuggestions([]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to accept all tracks');
    } finally {
      setAcceptingAll(false);
    }
  };

  const handleClear = () => {
    setSuggestions([]);
    setProfile(null);
    setError(null);
    setLlmQueries([]);
    setShowReasoning(false);
    setLockedHeight(null);
    // Also clear the cache for the current mode
    resultsCacheRef.current[mode] = { ...emptyCache };
  };

  const canGenerate = (() => {
    if (!hasConnectedServices || loading) return false;
    if (mode === 'requests') return hasAcceptedRequests;
    if (mode === 'template') return !!selectedPlaylist;
    if (mode === 'llm') return llmPrompt.trim().length >= 3;
    return false;
  })();

  // Derive short display name from model ID (e.g., "claude-haiku-4-5-20251001" → "Haiku 4.5")
  const modelDisplayName = (() => {
    if (!llmModel) return 'AI';
    const m = llmModel.toLowerCase();
    if (m.includes('haiku')) {
      const ver = m.match(/haiku-(\d+)-(\d+)/);
      return ver ? `Haiku ${ver[1]}.${ver[2]}` : 'Haiku';
    }
    if (m.includes('sonnet')) {
      const ver = m.match(/sonnet-(\d+)-(\d+)/);
      return ver ? `Sonnet ${ver[1]}.${ver[2]}` : 'Sonnet';
    }
    if (m.includes('opus')) {
      const ver = m.match(/opus-(\d+)-(\d+)/);
      return ver ? `Opus ${ver[1]}.${ver[2]}` : 'Opus';
    }
    return 'AI';
  })();

  const modeButtonStyle = (active: boolean) => ({
    padding: '0.25rem 0.5rem',
    fontSize: '0.75rem',
    border: 'none',
    borderRadius: '0.25rem',
    cursor: 'pointer' as const,
    background: active ? 'var(--color-primary)' : 'var(--surface-raised)',
    color: active ? '#fff' : 'var(--text-secondary)',
  });

  return (
    <div className="card" style={{ marginBottom: '1rem', padding: '1rem', overflow: 'visible' }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: '0.75rem',
      }}>
        <span style={{ fontWeight: 600 }}>Song Suggestions</span>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {suggestions.length > 0 && (
            <>
              <button
                className="btn btn-sm"
                style={{ background: 'var(--color-success)', color: 'white' }}
                onClick={handleAcceptAll}
                disabled={acceptingAll || loading}
              >
                {acceptingAll ? 'Accepting...' : 'Accept All'}
              </button>
              <button
                className="btn btn-sm"
                style={{ background: 'var(--text-tertiary)', color: 'white' }}
                onClick={handleClear}
                disabled={loading}
              >
                Clear
              </button>
            </>
          )}
          <Tooltip
            description={!canGenerate ? (
              !hasConnectedServices ? 'Link Tidal or Beatport first'
                : mode === 'requests' && !hasAcceptedRequests ? 'Accept some requests first'
                : mode === 'template' && !selectedPlaylist ? 'Select a playlist first'
                : mode === 'llm' && llmPrompt.trim().length < 3 ? 'Enter a prompt (3+ characters)'
                : loading ? 'Generation in progress'
                : undefined
            ) : undefined}
          >
            <button
              className={`btn btn-primary btn-sm${
                generateState === 'working' ? ' btn-generating' : ''
              }${generateState === 'complete' ? ' btn-complete' : ''
              }${generateState === 'idle' && !loading ? ' btn-complete-fade' : ''}`}
              onClick={handleGenerate}
              disabled={!canGenerate}
            >
              {generateState === 'working'
                ? 'Working...'
                : generateState === 'complete'
                  ? 'Complete!'
                  : 'Generate'}
            </button>
          </Tooltip>
        </div>
      </div>

      {/* Mode toggle */}
      {hasConnectedServices && (
        <div style={{ display: 'flex', gap: '0.25rem', marginBottom: '0.75rem' }}>
          <button
            style={modeButtonStyle(mode === 'requests')}
            onClick={() => handleModeChange('requests')}
          >
            From Requests
          </button>
          <button
            style={modeButtonStyle(mode === 'template')}
            onClick={() => handleModeChange('template')}
          >
            From Playlist
          </button>
          <Tooltip description={!llmAvailable ? 'Generate suggestions first to unlock AI Assist' : undefined}>
            <button
              style={{
                ...modeButtonStyle(mode === 'llm'),
                ...((!llmAvailable && mode !== 'llm') ? { opacity: 0.4, cursor: 'not-allowed' } : {}),
              }}
              onClick={() => llmAvailable && handleModeChange('llm')}
              disabled={!llmAvailable && mode !== 'llm'}
            >
              AI Assist
            </button>
          </Tooltip>
        </div>
      )}

      {/* LLM prompt input */}
      {mode === 'llm' && hasConnectedServices && (
        <div style={{ marginBottom: '0.75rem' }}>
          <input
            type="text"
            value={llmPrompt}
            onChange={(e) => setLlmPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && canGenerate) handleGenerate();
            }}
            placeholder="e.g., look at the requests and recommend some more like that, 90s hip hop vibes, songs like Sandstorm by Darude..."
            style={{
              width: '100%',
              padding: '0.5rem',
              borderRadius: '0.375rem',
              background: 'var(--card)',
              color: 'var(--text)',
              border: '1px solid var(--border)',
              fontSize: '0.875rem',
              boxSizing: 'border-box',
            }}
          />
        </div>
      )}

      {/* Playlist selector in template mode */}
      {mode === 'template' && hasConnectedServices && (
        <div style={{ marginBottom: '0.75rem' }}>
          {loadingPlaylists ? (
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: 0 }}>
              Loading playlists...
            </p>
          ) : playlists.length > 0 ? (
            <select
              value={selectedPlaylist || ''}
              onChange={(e) => setSelectedPlaylist(e.target.value || null)}
              style={{
                width: '100%',
                padding: '0.5rem',
                borderRadius: '0.375rem',
                background: 'var(--card)',
                color: 'var(--text)',
                border: '1px solid var(--border)',
                fontSize: '0.875rem',
              }}
            >
              <option value="">Select a playlist...</option>
              {playlists.map((p) => (
                <option key={`${p.source}:${p.id}`} value={`${p.source}:${p.id}`}>
                  [{p.source}] {p.name} ({p.num_tracks} tracks)
                </option>
              ))}
            </select>
          ) : playlistsLoaded ? (
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: 0 }}>
              No playlists found on connected services.
            </p>
          ) : null}
        </div>
      )}

      {!hasConnectedServices && (
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: 0 }}>
          Link Tidal or Beatport to get song suggestions.
        </p>
      )}

      {hasConnectedServices && mode === 'requests' && !hasAcceptedRequests
        && suggestions.length === 0 && (
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: 0 }}>
          Accept some requests first to build a music profile.
        </p>
      )}

      {error && (
        <div style={{ color: 'var(--color-danger)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
          {error}
        </div>
      )}

      {/* LLM reasoning section */}
      {llmQueries.length > 0 && (
        <div style={{ marginBottom: '0.75rem' }}>
          <button
            onClick={() => setShowReasoning(!showReasoning)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              fontSize: '0.8rem',
              cursor: 'pointer',
              padding: 0,
              textDecoration: 'underline',
            }}
          >
            {showReasoning ? 'Hide' : 'Show'} AI reasoning ({llmQueries.length} {llmQueries.length === 1 ? 'query' : 'queries'})
          </button>
          {showReasoning && (
            <div style={{
              marginTop: '0.5rem',
              padding: '0.5rem',
              borderRadius: '0.375rem',
              background: 'var(--surface-raised)',
              fontSize: '0.8rem',
              color: 'var(--text-secondary)',
            }}>
              {llmQueries.map((q, i) => (
                <div key={i} style={{ marginBottom: i < llmQueries.length - 1 ? '0.5rem' : 0 }}>
                  <div style={{ color: 'var(--text)', fontWeight: 500 }}>
                    {q.search_query}
                    {q.target_bpm && <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}> {q.target_bpm} BPM</span>}
                    {q.target_key && <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}> {q.target_key}</span>}
                    {q.target_genre && <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}> {q.target_genre}</span>}
                  </div>
                  {q.reasoning && (
                    <div style={{ fontStyle: 'italic', marginTop: '0.125rem' }}>{q.reasoning}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {profile && (
        <div style={{
          fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.75rem',
          display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center',
        }}>
          {profile.avg_bpm && (
            <span style={{ fontSize: '0.75rem' }}>~{Math.round(profile.avg_bpm)} BPM</span>
          )}
          {profile.dominant_keys.map((k) => (
            <KeyBadge key={k} musicalKey={k} />
          ))}
          {profile.dominant_genres.length > 0 && (
            <span>{profile.dominant_genres.join(', ')}</span>
          )}
          <Tooltip description="Tracks with BPM, key, and genre metadata available for scoring" delay={100}>
            <span style={{ cursor: 'help' }}>
              {profile.enriched_count}/{profile.track_count} with metadata
            </span>
          </Tooltip>
        </div>
      )}

      <div
        ref={suggestionsContainerRef}
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
          minHeight: lockedHeight ? `${lockedHeight}px` : '200px',
          maxHeight: '600px',
          overflowY: 'auto',
        }}
      >
        {suggestions.map((track) => {
            const trackKey = `${track.artist}-${track.title}`;
            const isAccepting = acceptingId === trackKey;
            return (
              <div
                key={trackKey}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.75rem',
                  padding: '0.5rem',
                  borderRadius: '0.375rem',
                  background: 'var(--card)',
                }}
              >
                {track.cover_url && (
                  <img
                    src={track.cover_url}
                    alt=""
                    style={{
                      width: 40, height: 40,
                      borderRadius: '0.25rem', objectFit: 'cover',
                      flexShrink: 0,
                    }}
                  />
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    display: 'flex', alignItems: 'baseline', gap: '0.375rem',
                  }}>
                    <span style={{
                      fontWeight: 500, fontSize: '0.875rem',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {track.artist} &mdash; {track.title}
                    </span>
                    {safeExternalUrl(track.url) && (
                      <a
                        href={safeExternalUrl(track.url)}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ fontSize: '0.75rem', flexShrink: 0 }}
                      >
                        ↗
                      </a>
                    )}
                  </div>
                  <div style={{
                    display: 'flex', gap: '0.375rem', flexWrap: 'wrap',
                    alignItems: 'center',
                  }}>
                    <BpmBadge
                      bpm={track.bpm}
                      avgBpm={profile?.avg_bpm ?? suggestionBpmContext.average}
                      isOutlier={track.bpm != null ? suggestionBpmContext.isOutlier(track.bpm) : false}
                    />
                    <KeyBadge musicalKey={track.key} />
                    <GenreBadge genre={track.genre} />
                    {/* Source badge */}
                    <span style={{
                      background: track.source === 'beatport' ? '#00b85533' : track.source === 'tidal' ? '#0066ff33' : '#1db95433',
                      color: track.source === 'beatport' ? '#00b855' : track.source === 'tidal' ? '#6699ff' : '#1db954',
                      padding: '0.0625rem 0.375rem',
                      borderRadius: '0.25rem',
                      fontSize: '0.625rem',
                      fontWeight: 600,
                      textTransform: 'uppercase',
                    }}>
                      {track.source === 'beatport' ? 'BP' : track.source === 'tidal' ? 'TL' : 'SP'}
                    </span>
                    {/* Score indicator with component breakdown tooltip */}
                    <Tooltip
                      title={`Match: ${Math.round(track.score * 100)}%`}
                      description={`BPM: ${Math.round(track.bpm_score * 100)}%  |  Key: ${Math.round(track.key_score * 100)}%  |  Genre: ${Math.round(track.genre_score * 100)}%`}
                      maxWidth={200}
                      delay={100}
                    >
                      <span
                        style={{
                          background: track.score >= 0.8 ? 'var(--color-success-subtle)' : track.score >= 0.6 ? 'var(--color-warning-subtle)' : 'var(--surface-raised)',
                          color: track.score >= 0.8 ? 'var(--color-success)' : track.score >= 0.6 ? 'var(--color-warning)' : 'var(--text-secondary)',
                          padding: '0.0625rem 0.375rem',
                          borderRadius: '0.25rem',
                          fontSize: '0.625rem',
                          fontWeight: 600,
                          cursor: 'help',
                        }}
                      >
                        {Math.round(track.score * 100)}%
                      </span>
                    </Tooltip>
                    {track.mb_verified && (
                      <span style={{
                        background: 'var(--color-success)',
                        color: '#fff',
                        padding: '0.0625rem 0.375rem',
                        borderRadius: '0.25rem',
                        fontSize: '0.625rem',
                        fontWeight: 600,
                      }}>
                        Verified Artist
                      </span>
                    )}
                    {mode === 'llm' && llmModel && (
                      <span style={{
                        background: 'var(--color-status-accepted)',
                        color: '#fff',
                        padding: '0.0625rem 0.375rem',
                        borderRadius: '0.25rem',
                        fontSize: '0.625rem',
                        fontWeight: 600,
                      }}>
                        {modelDisplayName} Recommended
                      </span>
                    )}
                  </div>
                  <PreviewPlayer data={{
                    source: track.source,
                    sourceUrl: track.url,
                  }} />
                </div>
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--color-success)', color: 'white', flexShrink: 0 }}
                  onClick={() => handleAccept(track)}
                  disabled={isAccepting || acceptingAll}
                >
                  {isAccepting ? '...' : 'Accept'}
                </button>
              </div>
            );
          })}
      </div>
    </div>
  );
}
