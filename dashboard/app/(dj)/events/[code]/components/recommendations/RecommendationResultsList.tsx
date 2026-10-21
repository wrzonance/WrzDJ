'use client';

import { useMemo, type RefObject } from 'react';
import { Tooltip } from '@/components/Tooltip';
import { KeyBadge, BpmBadge, GenreBadge } from '@/components/MusicBadges';
import { PreviewPlayer } from '@/components/PreviewPlayer';
import { computeBpmContext } from '@/lib/bpm-stats';
import { safeExternalUrl } from '@/lib/safe-url';
import type { RecommendedTrack } from '@/lib/api/types';
import type { RecommendationMode } from './useRecommendationResults';

interface RecommendationResultsListProps {
  suggestions: RecommendedTrack[];
  profileAverageBpm: number | null;
  mode: RecommendationMode;
  llmModel: string;
  acceptingId: string | null;
  hasPendingAcceptance: boolean;
  lockedHeight: number | null;
  containerRef: RefObject<HTMLDivElement | null>;
  onAcceptTrack: (track: RecommendedTrack) => Promise<void>;
}

function modelDisplayName(model: string): string {
  const modelId = model.toLowerCase();
  for (const providerModel of ['haiku', 'sonnet', 'opus']) {
    if (!modelId.includes(providerModel)) continue;
    const version = modelId.match(new RegExp(`${providerModel}-(\\d+)-(\\d+)`));
    const name = providerModel[0].toUpperCase() + providerModel.slice(1);
    return version ? `${name} ${version[1]}.${version[2]}` : name;
  }
  return model;
}

export function RecommendationResultsList({
  suggestions,
  profileAverageBpm,
  mode,
  llmModel,
  acceptingId,
  hasPendingAcceptance,
  lockedHeight,
  containerRef,
  onAcceptTrack,
}: RecommendationResultsListProps) {
  const suggestionBpmContext = useMemo(() => {
    const bpms = suggestions
      .map((suggestion) => suggestion.bpm)
      .filter((bpm): bpm is number => bpm != null);
    return computeBpmContext(bpms);
  }, [suggestions]);
  const displayModelName = llmModel ? modelDisplayName(llmModel) : '';

  return (
    <div
      ref={containerRef}
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
                  avgBpm={profileAverageBpm ?? suggestionBpmContext.average}
                  isOutlier={track.bpm != null ? suggestionBpmContext.isOutlier(track.bpm) : false}
                />
                <KeyBadge musicalKey={track.key} />
                <GenreBadge genre={track.genre} />
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
                    color: 'var(--text-on-bright-accent)',
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
                    color: 'var(--text-on-status-accepted)',
                    padding: '0.0625rem 0.375rem',
                    borderRadius: '0.25rem',
                    fontSize: '0.625rem',
                    fontWeight: 600,
                  }}>
                    {displayModelName} Recommended
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
              onClick={() => void onAcceptTrack(track)}
              disabled={hasPendingAcceptance || isAccepting}
            >
              {isAccepting ? '...' : 'Accept'}
            </button>
          </div>
        );
      })}
    </div>
  );
}
