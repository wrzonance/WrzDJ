'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import { CollectionFormFields, collectionSchema } from '@/components/events/collection/CollectionFormFields';
import type { PreEventEventShape } from './PreEventEventShape';
import TidalCollectionSyncPanel from './TidalCollectionSyncPanel';

interface Props {
  event: PreEventEventShape;
  tidalConnected: boolean;
  tidalIntegrationEnabled: boolean;
  onEventChange: (next: Partial<PreEventEventShape>) => void;
}

function toDatetimeLocal(iso: string | null): string {
  if (!iso) return '';
  return iso.slice(0, 16);
}

function toIso(local: string): string | null {
  if (!local) return null;
  return new Date(local).toISOString();
}

export default function CollectionConfigPanel({ event, tidalConnected, tidalIntegrationEnabled, onEventChange }: Props) {
  const [collectionOpensAt, setCollectionOpensAt] = useState(
    toDatetimeLocal(event.collection_opens_at),
  );
  const [liveStartsAt, setLiveStartsAt] = useState(toDatetimeLocal(event.live_starts_at));
  const [submissionCap, setSubmissionCap] = useState(event.submission_cap_per_guest);
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsSaved, setSettingsSaved] = useState(false);

  async function handleSaveSettings(e: React.FormEvent) {
    e.preventDefault();
    setSettingsError(null);
    setSettingsSaved(false);

    const parsed = collectionSchema.safeParse({
      collection_opens_at: collectionOpensAt || undefined,
      live_starts_at: liveStartsAt || undefined,
      submission_cap_per_guest: submissionCap,
    });

    if (!parsed.success) {
      setSettingsError(parsed.error.issues[0].message);
      return;
    }

    setSavingSettings(true);
    try {
      const resp = await api.patchCollectionSettings(event.code, {
        collection_opens_at: toIso(collectionOpensAt),
        live_starts_at: toIso(liveStartsAt),
        submission_cap_per_guest: submissionCap,
      });
      onEventChange(resp);
      setSettingsSaved(true);
      setTimeout(() => setSettingsSaved(false), 3000);
    } catch (err) {
      setSettingsError(err instanceof Error ? err.message : 'Failed to save settings');
    } finally {
      setSavingSettings(false);
    }
  }

  return (
    <div>
      <div className="card" style={{ marginBottom: '1.25rem' }}>
        <h3 style={{ marginBottom: '0.75rem', fontSize: '1rem' }}>Collection Settings</h3>
        <form onSubmit={handleSaveSettings}>
          <CollectionFormFields
            collectionOpensAt={collectionOpensAt}
            onCollectionOpensAtChange={setCollectionOpensAt}
            liveStartsAt={liveStartsAt}
            onLiveStartsAtChange={setLiveStartsAt}
            submissionCap={submissionCap}
            onSubmissionCapChange={setSubmissionCap}
            error={settingsError}
          />
          {settingsSaved && (
            <p style={{ color: 'var(--color-success)', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              Settings saved.
            </p>
          )}
          <button type="submit" className="btn btn-primary btn-sm" disabled={savingSettings}>
            {savingSettings ? 'Saving…' : 'Save settings'}
          </button>
        </form>
      </div>

      {tidalConnected && tidalIntegrationEnabled && (
        <TidalCollectionSyncPanel event={event} onEventChange={onEventChange} />
      )}
    </div>
  );
}
