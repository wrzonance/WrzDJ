'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { api, Event } from '@/lib/api';
import { useHelp } from '@/lib/help/HelpContext';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';
import { CollectionFieldset, collectionSchema } from '@/components/CollectionFieldset';

const PAGE_ID = 'events';

export default function EventsPage() {
  const { isAuthenticated, isLoading, role, logout } = useAuth();
  const { hasSeenPage, startOnboarding } = useHelp();
  const router = useRouter();
  const [events, setEvents] = useState<Event[]>([]);
  const [loadingEvents, setLoadingEvents] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newEventName, setNewEventName] = useState('');
  const [creating, setCreating] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(new Set());
  const [deletingSelected, setDeletingSelected] = useState(false);

  // Pre-event collection state
  const [showCollection, setShowCollection] = useState(false);
  const [collectionOpensAt, setCollectionOpensAt] = useState('');
  const [liveStartsAt, setLiveStartsAt] = useState('');
  const [submissionCap, setSubmissionCap] = useState(0);
  const [collectionError, setCollectionError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    } else if (!isLoading && role === 'pending') {
      router.push('/pending');
    }
  }, [isAuthenticated, isLoading, role, router]);

  useEffect(() => {
    if (isAuthenticated) {
      loadEvents();
    }
  }, [isAuthenticated]);

  // Auto-trigger onboarding for first-time visitors
  useEffect(() => {
    if (!isLoading && isAuthenticated && !loadingEvents && !hasSeenPage(PAGE_ID)) {
      const timer = setTimeout(() => startOnboarding(PAGE_ID), 500);
      return () => clearTimeout(timer);
    }
  }, [isLoading, isAuthenticated, loadingEvents, hasSeenPage, startOnboarding]);

  const loadEvents = async () => {
    try {
      const data = await api.getEvents();
      setEvents(data);
    } catch {
      setErrorMsg('Failed to load events');
    } finally {
      setLoadingEvents(false);
    }
  };

  const handleCreateEvent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newEventName.trim()) return;

    // Validate collection settings before creating
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
    let createdEvent;
    try {
      createdEvent = await api.createEvent(newEventName);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to create event');
      setCreating(false);
      return;
    }

    // Show the event in the list immediately, even if collection settings fail —
    // the user can finish setup on the event's Pre-Event Voting tab.
    setEvents([createdEvent, ...events]);

    if (showCollection && (collectionOpensAt || liveStartsAt || submissionCap > 0)) {
      try {
        await api.patchCollectionSettings(createdEvent.code, {
          collection_opens_at: collectionOpensAt
            ? new Date(collectionOpensAt).toISOString()
            : null,
          live_starts_at: liveStartsAt
            ? new Date(liveStartsAt).toISOString()
            : null,
          submission_cap_per_guest: submissionCap,
        });
      } catch (err) {
        setErrorMsg(
          `Event "${createdEvent.name}" was created, but collection settings failed: ${
            err instanceof Error ? err.message : 'unknown error'
          }. Open the event and finish setup on the Pre-Event Voting tab.`,
        );
        setCreating(false);
        return;
      }
    }

    setNewEventName('');
    setShowCreate(false);
    setShowCollection(false);
    setCollectionOpensAt('');
    setLiveStartsAt('');
    setSubmissionCap(0);
    setCreating(false);
  };

  const toggleSelection = (code: string) => {
    setSelectedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedEvents.size === events.length) {
      setSelectedEvents(new Set());
    } else {
      setSelectedEvents(new Set(events.map((e) => e.code)));
    }
  };

  const handleBulkDelete = async () => {
    if (selectedEvents.size === 0) return;
    if (!window.confirm(`Delete ${selectedEvents.size} event${selectedEvents.size === 1 ? '' : 's'}? This cannot be undone.`)) return;

    setDeletingSelected(true);
    try {
      await api.bulkDeleteEvents([...selectedEvents]);
      setSelectedEvents(new Set());
      await loadEvents();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to delete events');
    } finally {
      setDeletingSelected(false);
    }
  };

  if (isLoading || !isAuthenticated) {
    return (
      <div className="container">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  return (
    <div className="container">
      <HelpButton page={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />

      {errorMsg && (
        <div style={{ background: 'var(--color-danger-subtle)', color: 'var(--color-danger)', padding: '0.75rem 1rem', borderRadius: '0.5rem', marginBottom: '1rem', fontSize: '0.875rem' }}>
          {errorMsg}
        </div>
      )}
      <HelpSpot spotId="events-header" page={PAGE_ID} order={1} title="Your Events" description="This is your events dashboard. All your DJ events appear here.">
        <div className="header">
          <h1>My Events</h1>
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
            {role === 'admin' && (
              <HelpSpot spotId="events-admin" page={PAGE_ID} order={3} title="Admin Panel" description="Access the admin panel to manage users, view all events, and configure integrations.">
                <Link href="/admin">
                  <button className="btn" style={{ background: 'var(--color-admin)', color: 'white' }}>Admin</button>
                </Link>
              </HelpSpot>
            )}
            <HelpSpot spotId="events-create" page={PAGE_ID} order={2} title="Create Event" description="Click to create a new event. Each event gets a unique code and QR that guests scan to submit requests.">
              <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
                Create Event
              </button>
            </HelpSpot>
            <a
              href="https://github.com/thewrz/WrzDJ/releases/latest"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-sm"
              style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}
            >
              Bridge App
            </a>
            <Link href="/account" className="btn" style={{ background: 'var(--surface-raised)', textDecoration: 'none', color: 'var(--text)' }}>
              Account
            </Link>
            <button className="btn" style={{ background: 'var(--surface-raised)' }} onClick={logout}>
              Logout
            </button>
          </div>
        </div>
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

      {loadingEvents ? (
        <div className="loading">Loading events...</div>
      ) : events.length === 0 ? (
        <div className="card" style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--text-secondary)' }}>No events yet. Create your first event!</p>
        </div>
      ) : (
        <>
          {events.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={selectionMode}
                  onChange={(e) => {
                    setSelectionMode(e.target.checked);
                    if (!e.target.checked) setSelectedEvents(new Set());
                  }}
                  style={{ accentColor: 'var(--color-accent-checkbox)' }}
                  aria-label="Advanced"
                />
                Advanced
              </label>
              {selectionMode && (
                <>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={selectedEvents.size === events.length && events.length > 0}
                      onChange={toggleSelectAll}
                      style={{ accentColor: 'var(--color-accent-checkbox)' }}
                      aria-label="Select All"
                    />
                    Select All
                  </label>
                  {selectedEvents.size > 0 && (
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={handleBulkDelete}
                      disabled={deletingSelected}
                    >
                      {deletingSelected ? 'Deleting...' : `Delete Selected (${selectedEvents.size})`}
                    </button>
                  )}
                </>
              )}
            </div>
          )}
          <HelpSpot spotId="events-grid" page={PAGE_ID} order={4} title="Event Cards" description="Your events appear as cards. Click any card to manage its request queue, sync settings, and kiosk controls.">
            <div className="event-grid">
              {events.map((event) => (
                selectionMode ? (
                  <div
                    key={event.id}
                    className="event-card"
                    style={{
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '0.75rem',
                      outline: selectedEvents.has(event.code) ? '2px solid var(--color-primary)' : 'none',
                    }}
                    onClick={() => toggleSelection(event.code)}
                  >
                    <input
                      type="checkbox"
                      checked={selectedEvents.has(event.code)}
                      onChange={() => toggleSelection(event.code)}
                      onClick={(e) => e.stopPropagation()}
                      style={{ accentColor: 'var(--color-accent-checkbox)', width: '1rem', height: '1rem', marginTop: '0.25rem', flexShrink: 0 }}
                      aria-label={`Select event ${event.code}`}
                    />
                    <div>
                      <h3>{event.name}</h3>
                      <div className="code">{event.code}</div>
                      <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                        Expires: {new Date(event.expires_at).toLocaleString()}
                      </p>
                      {!event.is_active && (
                        <span className="badge badge-rejected" style={{ marginTop: '0.5rem' }}>
                          Inactive
                        </span>
                      )}
                    </div>
                  </div>
                ) : (
                  <Link key={event.id} href={`/events/${event.code}`}>
                    <div className="event-card" style={{ cursor: 'pointer' }}>
                      <h3>{event.name}</h3>
                      <div className="code">{event.code}</div>
                      <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                        Expires: {new Date(event.expires_at).toLocaleString()}
                      </p>
                      {!event.is_active && (
                        <span className="badge badge-rejected" style={{ marginTop: '0.5rem' }}>
                          Inactive
                        </span>
                      )}
                    </div>
                  </Link>
                )
              ))}
            </div>
          </HelpSpot>
        </>
      )}
    </div>
  );
}
