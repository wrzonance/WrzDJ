'use client';

import type { SongRequest } from '@/lib/api/types';
import { Tooltip } from '@/components/Tooltip';
import { SyncStatusBadges } from '../providers/SyncStatusBadges';
import { KeyBadge, BpmBadge, GenreBadge } from '@/components/MusicBadges';
import { PreviewPlayer } from '@/components/PreviewPlayer';
import { getRequestEmphasisStyle } from '@/lib/request-emphasis';
import { safeExternalUrl } from '@/lib/safe-url';
import { getVoteHeatStyle } from '@/lib/vote-heat';
import { formatRequestTimestamp } from '@/lib/format-time';
import { formatPriorityScore, getPriorityScoreColor } from '@/lib/priority-score';
import type { RequestRowActions, RequestRowPresentation } from './requestQueueTypes';

interface RequestQueueRowProps {
  request: SongRequest;
  actions: RequestRowActions;
  presentation: RequestRowPresentation;
}

export function RequestQueueRow({ request, actions, presentation }: RequestQueueRowProps) {
  const { connectedServices, syncingRequest, onSyncToTidal, onOpenTidalPicker, onScrollToSyncReport,
    updating, onUpdateStatus, onRefreshMetadata, onDeleteRequest, deletingRequest, refreshingRequest,
  } = actions;
  const { bpmContext, sortField, advancedMode, isExpiredOrArchived } = presentation;
  const emphasis = getRequestEmphasisStyle(request.status);
  const heat = getVoteHeatStyle(request.vote_count);

  return (
    <div
      id={`request-${request.id}`}
      className="request-item"
      style={{
        ...emphasis,
        ...heat,
        // Status emphasis background takes priority over vote heat
        ...(emphasis.background ? { background: emphasis.background } : {}),
      }}
    >
      {request.artwork_url ? (
        <img
          src={request.artwork_url}
          alt=""
          style={{
            width: 40,
            height: 40,
            borderRadius: '0.25rem',
            objectFit: 'cover',
            flexShrink: 0,
            marginRight: '0.625rem',
          }}
        />
      ) : (
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: '0.25rem',
            background: 'var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            marginRight: '0.625rem',
            fontSize: '1rem',
            color: 'var(--text-tertiary)',
          }}
        >
          ♪
        </div>
      )}
      <div className="request-info">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.375rem' }}>
          <h3 style={{ margin: 0 }}>{request.song_title}</h3>
          {safeExternalUrl(request.source_url) && (
            <a
              href={safeExternalUrl(request.source_url)}
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: '0.75rem', flexShrink: 0 }}
            >
              ↗
            </a>
          )}
        </div>
        <p>{request.artist}</p>
        {(request.bpm || request.musical_key || request.genre) && (
          <div style={{
            display: 'flex', gap: '0.375rem', marginTop: '0.25rem',
            flexWrap: 'wrap', alignItems: 'center',
          }}>
            <BpmBadge
              bpm={request.bpm}
              avgBpm={bpmContext.average}
              isOutlier={request.bpm != null ? bpmContext.isOutlier(request.bpm) : false}
            />
            <KeyBadge musicalKey={request.musical_key} />
            <GenreBadge genre={request.genre} />
          </div>
        )}
        {request.nickname && (
          <div className="request-nickname">
            <span className="nickname-icon">&#128100;</span> {request.nickname}
          </div>
        )}
        {request.note && <div className="note">{request.note}</div>}
        <PreviewPlayer data={{ source: request.source, sourceUrl: request.source_url }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem' }}>
          <p style={{ fontSize: '0.75rem', margin: 0 }}>{formatRequestTimestamp(request.created_at)}</p>
          {request.vote_count > 0 && (
            <span
              style={{
                background: request.vote_count >= 5 ? 'var(--color-warning)' : 'var(--color-primary)',
                color: request.vote_count >= 5
                  ? 'var(--text-on-warning)'
                  : 'var(--text-on-primary)',
                padding: '0.125rem 0.5rem',
                borderRadius: '1rem',
                fontSize: '0.7rem',
                fontWeight: 600,
              }}
            >
              {request.vote_count} {request.vote_count === 1 ? 'vote' : 'votes'}
            </span>
          )}
          {sortField === 'best_match' && request.priority_score != null && (
            <Tooltip description="Combines votes, wait time, harmonic compatibility, and BPM energy match" delay={100}>
              <span
                style={{
                  background: getPriorityScoreColor(request.priority_score),
                  color: 'var(--text-on-priority-score)',
                  padding: '0.125rem 0.5rem',
                  borderRadius: '1rem',
                  fontSize: '0.7rem',
                  fontWeight: 600,
                  cursor: 'help',
                }}
              >
                {formatPriorityScore(request.priority_score)}
              </span>
            </Tooltip>
          )}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <SyncStatusBadges
          request={request}
          connectedServices={connectedServices}
          syncingRequest={syncingRequest}
          onSyncToTidal={onSyncToTidal}
          onOpenTidalPicker={onOpenTidalPicker}
          onScrollToSyncReport={onScrollToSyncReport}
        />
        <span className={`badge badge-${request.status}`}>
          {request.status === 'playing' ? 'manually playing' : request.status}
        </span>
        {!isExpiredOrArchived && (
          <div className="request-actions">
            {request.status === 'new' && (
              <>
                <button
                  className="btn btn-success btn-sm"
                  onClick={() => onUpdateStatus(request.id, 'accepted')}
                  disabled={updating !== null}
                >
                  Accept
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => onUpdateStatus(request.id, 'rejected')}
                  disabled={updating !== null}
                >
                  Reject
                </button>
              </>
            )}
            {request.status === 'accepted' && (
              <>
                {(!actions.bridgeConnected || advancedMode) && (
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => onUpdateStatus(request.id, 'playing')}
                    disabled={updating !== null}
                  >
                    Mark Playing
                  </button>
                )}
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => onUpdateStatus(request.id, 'rejected')}
                  disabled={updating !== null}
                >
                  Reject
                </button>
              </>
            )}
            {request.status === 'playing' && (
              <button
                className="btn btn-warning btn-sm"
                onClick={() => onUpdateStatus(request.id, 'played')}
                disabled={updating !== null}
              >
                Played
              </button>
            )}
            {advancedMode && (
              <>
                <Tooltip description="Re-fetch BPM, key, and genre from external services">
                  <button
                    className="btn btn-sm"
                    style={{ background: 'var(--surface-raised)', fontSize: '0.7rem' }}
                    onClick={() => onRefreshMetadata?.(request.id)}
                    disabled={refreshingRequest === request.id}
                  >
                    {refreshingRequest === request.id ? '...' : 'Refresh'}
                  </button>
                </Tooltip>
                <button
                  className="btn btn-sm"
                  style={{ background: 'var(--color-danger-subtle)', fontSize: '0.7rem' }}
                  onClick={() => {
                    if (window.confirm(`Delete "${request.song_title}" by ${request.artist}?`)) {
                      onDeleteRequest?.(request.id);
                    }
                  }}
                  disabled={deletingRequest === request.id}
                >
                  {deletingRequest === request.id ? '...' : 'Delete'}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
