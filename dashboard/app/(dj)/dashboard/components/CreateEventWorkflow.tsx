'use client';

import { useState, type FormEvent } from 'react';
import { api } from '@/lib/api';
import type { Event } from '@/lib/api/types';
import { HelpSpot } from '@/components/help/HelpSpot';
import { CollectionFieldset, collectionSchema } from '@/components/events/collection/CollectionFieldset';
import { useLocale } from '@/lib/locale';

interface CreateEventWorkflowProps {
  onCreated: (event: Event) => void;
  onError: (message: string) => void;
}

export function CreateEventWorkflow({ onCreated, onError }: CreateEventWorkflowProps) {
  const { locale, messages } = useLocale();
  const [showCreate, setShowCreate] = useState(false);
  const [newEventName, setNewEventName] = useState('');
  const [creating, setCreating] = useState(false);
  const [showCollection, setShowCollection] = useState(false);
  const [collectionOpensAt, setCollectionOpensAt] = useState('');
  const [liveStartsAt, setLiveStartsAt] = useState('');
  const [submissionCap, setSubmissionCap] = useState(0);
  const [collectionError, setCollectionError] = useState<string | null>(null);

  const handleCreateEvent = async (event: FormEvent) => {
    event.preventDefault();
    if (!newEventName.trim()) return;

    if (showCollection) {
      const parsed = collectionSchema.safeParse({
        collection_opens_at: collectionOpensAt || undefined,
        live_starts_at: liveStartsAt || undefined,
        submission_cap_per_guest: submissionCap,
      });
      if (!parsed.success) {
        setCollectionError(parsed.error.issues[0].message);
        return;
      }
    }

    setCollectionError(null);
    setCreating(true);
    try {
      const createdEvent = await api.createEvent(newEventName);
      onCreated(createdEvent);

      if (showCollection && (collectionOpensAt || liveStartsAt || submissionCap > 0)) {
        try {
          await api.patchCollectionSettings(createdEvent.code, {
            collection_opens_at: collectionOpensAt
              ? new Date(collectionOpensAt).toISOString()
              : null,
            live_starts_at: liveStartsAt ? new Date(liveStartsAt).toISOString() : null,
            submission_cap_per_guest: submissionCap,
          });
        } catch (error) {
          onError(
            `Event "${createdEvent.name}" was created, but collection settings failed: ${
              error instanceof Error ? error.message : 'unknown error'
            }. Open the event and finish setup on the Pre-Event Voting tab.`,
          );
          return;
        }
      }

      setNewEventName('');
      setShowCreate(false);
      setShowCollection(false);
      setCollectionOpensAt('');
      setLiveStartsAt('');
      setSubmissionCap(0);
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Failed to create event');
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <HelpSpot
        spotId="events-create"
        page="dashboard"
        order={2}
        title="Create Event"
        description="Click to create a new event. Each event gets a unique code and QR that guests scan to submit requests."
      >
        <button className="btn btn-primary" lang={locale} onClick={() => setShowCreate(true)}>
          {messages.dashboard.createEvent}
        </button>
      </HelpSpot>

      {showCreate && (
        <div className="card" style={{ marginBottom: '2rem' }}>
          <h2 style={{ marginBottom: '1rem' }}>Create New Event</h2>
          <form onSubmit={handleCreateEvent}>
            <div className="form-group">
              <label htmlFor="eventName">Event Name</label>
              <input
                id="eventName"
                type="text"
                className="input"
                placeholder="Friday Night Party"
                value={newEventName}
                onChange={(e) => setNewEventName(e.target.value)}
                maxLength={100}
                required
              />
            </div>
            <CollectionFieldset
              enabled={showCollection}
              onEnabledChange={setShowCollection}
              collectionOpensAt={collectionOpensAt}
              onCollectionOpensAtChange={setCollectionOpensAt}
              liveStartsAt={liveStartsAt}
              onLiveStartsAtChange={setLiveStartsAt}
              submissionCap={submissionCap}
              onSubmissionCapChange={setSubmissionCap}
              error={collectionError}
            />
            <div style={{ display: 'flex', gap: '1rem' }}>
              <button type="submit" className="btn btn-primary" disabled={creating}>
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button
                type="button"
                className="btn"
                style={{ background: 'var(--surface-raised)' }}
                onClick={() => setShowCreate(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
