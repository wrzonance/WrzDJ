'use client';

import { useState, useRef, useEffect } from 'react';
import { Tooltip } from '@/components/Tooltip';
import { KeyBadge } from '@/components/MusicBadges';
import { RecommendationResultsList } from './RecommendationResultsList';
import { useRecommendationPlaylists } from './useRecommendationPlaylists';
import { useRecommendationResults, type RecommendationMode } from './useRecommendationResults';
import type { RecommendedTrack } from '@/lib/api/types';

type Mode = RecommendationMode;

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

  const {
    mode,
    suggestions,
    profile,
    llmQueries,
    llmModel,
    loading,
    error,
    setError,
    llmAvailable,
    generateState,
    acceptingId,
    acceptingAll,
    hasPendingAcceptance,
    generate,
    acceptTrack,
    acceptAll,
    clearCurrentMode,
    changeMode,
  } = useRecommendationResults(code, onAcceptTrack);

  // Template playlist state
  const {
    playlists,
    selectedPlaylist,
    setSelectedPlaylist,
    loadingPlaylists,
    playlistsLoaded,
    loadPlaylists,
  } = useRecommendationPlaylists(code, setError);

  // LLM state
  const [llmPrompt, setLlmPrompt] = useState('');
  const [showReasoning, setShowReasoning] = useState(false);

  // Ref for the suggestions list container (scroll position save/restore)
  const suggestionsContainerRef = useRef<HTMLDivElement>(null);

  // Lock container height during mode switches to prevent page-level scroll jumps
  const [lockedHeight, setLockedHeight] = useState<number | null>(null);

  useEffect(() => {
    setShowReasoning(false);
    setLockedHeight(null);
  }, [code]);

  const handleModeChange = (newMode: Mode) => {
    if (newMode === mode) return;

    // Lock container height to prevent page-level scroll jump
    if (suggestionsContainerRef.current) {
      setLockedHeight(suggestionsContainerRef.current.offsetHeight);
    }

    const savedScrollTop = changeMode(
      newMode,
      suggestionsContainerRef.current?.scrollTop ?? 0,
    );
    if (savedScrollTop === null) return;
    // Restore scroll position after DOM update
    requestAnimationFrame(() => {
      if (suggestionsContainerRef.current) {
        suggestionsContainerRef.current.scrollTop = savedScrollTop;
      }
    });

    setShowReasoning(false);
    if (newMode === 'template') {
      loadPlaylists();
    }
  };

  const handleGenerate = () => {
    void generate({ prompt: llmPrompt, selectedPlaylist });
  };

  const handleClear = () => {
    clearCurrentMode();
    setError(null);
    setShowReasoning(false);
    setLockedHeight(null);
  };

  const canGenerate = (() => {
    if (!hasConnectedServices || loading) return false;
    if (mode === 'requests') return hasAcceptedRequests;
    if (mode === 'template') return !!selectedPlaylist;
    if (mode === 'llm') return llmPrompt.trim().length >= 3;
    return false;
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
                onClick={() => void acceptAll()}
                disabled={hasPendingAcceptance || loading}
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

      <RecommendationResultsList
        suggestions={suggestions}
        profileAverageBpm={profile?.avg_bpm ?? null}
        mode={mode}
        llmModel={llmModel}
        acceptingId={acceptingId}
        hasPendingAcceptance={hasPendingAcceptance}
        lockedHeight={lockedHeight}
        containerRef={suggestionsContainerRef}
        onAcceptTrack={acceptTrack}
      />
    </div>
  );
}
