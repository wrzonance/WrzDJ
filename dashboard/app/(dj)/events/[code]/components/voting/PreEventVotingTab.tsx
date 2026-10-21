'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import CollectionConfigPanel from './CollectionConfigPanel';
import PendingReviewPanel from './PendingReviewPanel';
import type { PreEventEventShape as EventShape } from './PreEventEventShape';

interface Props {
  event: EventShape;
  tidalConnected: boolean;
  tidalIntegrationEnabled: boolean;
  onEventChange: (next: Partial<EventShape>) => void;
}

type ConfirmAction = 'force_collection' | 'force_live' | 'clear';

const CONFIRM_LABEL: Record<ConfirmAction, string> = {
  force_collection: 'Open collection now',
  force_live: 'Start live now',
  clear: 'Clear phase override',
};

export default function PreEventVotingTab({
  event,
  tidalConnected,
  tidalIntegrationEnabled,
  onEventChange,
}: Props) {
  const [confirming, setConfirming] = useState<ConfirmAction | null>(null);
  const [pendingTotal, setPendingTotal] = useState(0);

  async function applyOverride(value: 'force_collection' | 'force_live' | null) {
    const resp = await api.patchCollectionSettings(event.code, {
      collection_phase_override: value,
    });
    onEventChange(resp);
    setConfirming(null);
  }

  const shareUrl =
    typeof window !== 'undefined'
      ? `${window.location.origin}/collect/${event.code}`
      : `/collect/${event.code}`;

  return (
    <div style={{ padding: '1rem' }}>
      <h2 style={{ marginBottom: '1rem' }}>Pre-Event Voting</h2>

      {!event.collection_opens_at && !event.live_starts_at && (
        <div
          style={{
            padding: '0.875rem 1rem',
            background: 'var(--color-primary-subtle)',
            border: '1px solid var(--color-primary-subtle)',
            borderRadius: 8,
            color: 'var(--color-link)',
            marginBottom: '1.25rem',
            fontSize: '0.9rem',
          }}
        >
          Pre-event voting isn&apos;t enabled yet. Set the dates below to turn it
          on — guests can then visit the share link to suggest and upvote songs
          ahead of the live event.
        </div>
      )}

      <div className="pre-event-stats">
        <div className="pre-event-stat">
          <div className="pre-event-stat-label">Current phase</div>
          <div className="pre-event-stat-value">{event.phase.replace('_', ' ')}</div>
        </div>
        <div className="pre-event-stat">
          <div className="pre-event-stat-label">Pending review</div>
          <div className="pre-event-stat-value">{pendingTotal}</div>
        </div>
        <div className="pre-event-stat">
          <div className="pre-event-stat-label">Pick cap / guest</div>
          <div className="pre-event-stat-value">
            {event.submission_cap_per_guest === 0 ? '∞' : event.submission_cap_per_guest}
          </div>
        </div>
      </div>

      <div className="pre-event-share">
        <code>{shareUrl}</code>
        <button
          type="button"
          className="btn btn-sm"
          style={{ background: 'var(--border)', color: 'var(--text)' }}
          onClick={() => navigator.clipboard.writeText(shareUrl)}
        >
          Copy
        </button>
      </div>

      <CollectionConfigPanel
        event={event}
        tidalConnected={tidalConnected}
        tidalIntegrationEnabled={tidalIntegrationEnabled}
        onEventChange={onEventChange}
      />

      <div className="card" style={{ marginBottom: '1.25rem' }}>
        <h3 style={{ marginBottom: '0.75rem', fontSize: '1rem' }}>Phase controls</h3>
        <div className="pre-event-override-actions">
          <button
            type="button"
            className="btn btn-sm"
            style={{ background: 'var(--border)', color: 'var(--text)' }}
            onClick={() => setConfirming('force_collection')}
          >
            Open collection now
          </button>
          <button
            type="button"
            className="btn btn-sm btn-success"
            onClick={() => setConfirming('force_live')}
          >
            Start live now
          </button>
          <button
            type="button"
            className="btn btn-sm"
            style={{ background: 'var(--border)', color: 'var(--text)' }}
            onClick={() => setConfirming('clear')}
          >
            Clear override
          </button>
        </div>

        {confirming && (
          <div className="pre-event-confirm">
            <span>Confirm: {CONFIRM_LABEL[confirming]}?</span>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => applyOverride(confirming === 'clear' ? null : confirming)}
            >
              Confirm
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        )}
      </div>

      <PendingReviewPanel eventCode={event.code} onPendingTotalChange={setPendingTotal} />
    </div>
  );
}
