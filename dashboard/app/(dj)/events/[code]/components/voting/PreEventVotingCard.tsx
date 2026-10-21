'use client';

import { useState } from 'react';
import { api, type CollectionSettingsResponse } from '@/lib/api';
import {
  CollectionFieldset,
  collectionSchema,
} from '@/components/events/collection/CollectionFieldset';
import type { Event, ArchivedEvent } from '@/lib/api/types';

function toIso(local: string): string | null {
  if (!local) return null;
  return new Date(local).toISOString();
}

function toDatetimeLocal(iso: string | null | undefined): string {
  if (!iso) return '';
  return iso.slice(0, 16);
}

interface Props {
  event: Event | ArchivedEvent;
  onEnabled: (next: CollectionSettingsResponse) => void;
  onJumpToTab: () => void;
}

/**
 * Lives on the Event Management tab. Two modes:
 *   1. Voting NOT enabled (collection_opens_at is null) — surface the
 *      "Enable pre-event voting" toggle + date form inline.
 *   2. Voting enabled — show a status pill + button that jumps to the
 *      dedicated Pre-Event Voting tab where the full UI lives.
 */
export function PreEventVotingCard({ event, onEnabled, onJumpToTab }: Props) {
  const enabled = !!event.collection_opens_at || !!event.live_starts_at;

  const [showFields, setShowFields] = useState(false);
  const [opensAt, setOpensAt] = useState(toDatetimeLocal(event.collection_opens_at));
  const [liveAt, setLiveAt] = useState(toDatetimeLocal(event.live_starts_at));
  const [cap, setCap] = useState(event.submission_cap_per_guest ?? 15);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  if (enabled) {
    return (
      <div className="card">
        <h3 style={{ marginBottom: '0.5rem', fontSize: '1.05rem' }}>
          Pre-Event Voting
        </h3>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '0.75rem', fontSize: '0.875rem' }}>
          Voting is enabled. Manage dates, share link, phase overrides, and bulk-review
          on the dedicated tab.
        </p>
        <button type="button" className="btn btn-sm btn-primary" onClick={onJumpToTab}>
          Open Pre-Event Voting →
        </button>
      </div>
    );
  }

  async function handleSave() {
    if (!showFields) {
      setShowFields(true);
      return;
    }
    setError(null);
    const parsed = collectionSchema.safeParse({
      collection_opens_at: opensAt || undefined,
      live_starts_at: liveAt || undefined,
      submission_cap_per_guest: cap,
    });
    if (!parsed.success) {
      setError(parsed.error.issues[0].message);
      return;
    }
    if (!opensAt && !liveAt) {
      setError('Set at least an "opens at" or "live starts at" date.');
      return;
    }
    setSaving(true);
    try {
      const resp = await api.patchCollectionSettings(event.code, {
        collection_opens_at: toIso(opensAt),
        live_starts_at: toIso(liveAt),
        submission_cap_per_guest: cap,
      });
      onEnabled(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to enable pre-event voting');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <h3 style={{ marginBottom: '0.5rem', fontSize: '1.05rem' }}>
        Pre-Event Voting
      </h3>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '0.75rem', fontSize: '0.875rem' }}>
        Let guests suggest and upvote songs in advance via a dedicated link.
        At live-start, accepted picks flow into the regular request queue.
      </p>

      {showFields && (
        <CollectionFieldset
          enabled={true}
          onEnabledChange={(v) => {
            if (!v) setShowFields(false);
          }}
          collectionOpensAt={opensAt}
          onCollectionOpensAtChange={setOpensAt}
          liveStartsAt={liveAt}
          onLiveStartsAtChange={setLiveAt}
          submissionCap={cap}
          onSubmissionCapChange={setCap}
          error={error}
        />
      )}

      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button
          type="button"
          className="btn btn-sm btn-primary"
          onClick={handleSave}
          disabled={saving}
        >
          {showFields
            ? saving
              ? 'Enabling…'
              : 'Enable pre-event voting'
            : 'Set up pre-event voting'}
        </button>
        {showFields && (
          <button
            type="button"
            className="btn btn-sm"
            style={{ background: 'var(--border)', color: 'var(--text)' }}
            onClick={() => setShowFields(false)}
            disabled={saving}
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
