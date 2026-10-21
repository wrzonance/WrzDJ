'use client';

import { useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import type { Event } from '@/lib/api/types';
import { HelpSpot } from '@/components/help/HelpSpot';
import { useBulkEventDeletion } from '@/lib/useBulkEventDeletion';

export function DashboardEventList({
  events,
  loading,
  onEventsChange,
  onError,
}: {
  events: Event[];
  loading: boolean;
  onEventsChange: (events: Event[]) => void;
  onError: (message: string) => void;
}) {
  const [selectionMode, setSelectionMode] = useState(false);

  const loadEvents = async () => {
    try {
      onEventsChange(await api.getEvents());
    } catch {
      onError('Failed to load events');
    }
  };

  const {
    selectedEvents,
    deletingSelected,
    toggleEvent,
    toggleEvents,
    clearSelection,
    deleteSelected,
  } = useBulkEventDeletion({
    deleteEvents: api.bulkDeleteEvents,
    refreshEvents: loadEvents,
    onError,
  });

  if (loading) return <div className="loading">Loading events...</div>;
  if (events.length === 0) {
    return (
      <div className="card" style={{ textAlign: 'center' }}>
        <p style={{ color: 'var(--text-secondary)' }}>No events yet. Create your first event!</p>
      </div>
    );
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={selectionMode}
            onChange={(event) => {
              setSelectionMode(event.target.checked);
              if (!event.target.checked) clearSelection();
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
                onChange={() => toggleEvents(events.map((event) => event.code))}
                style={{ accentColor: 'var(--color-accent-checkbox)' }}
                aria-label="Select All"
              />
              Select All
            </label>
            {selectedEvents.size > 0 && (
              <button className="btn btn-sm btn-danger" onClick={deleteSelected} disabled={deletingSelected}>
                {deletingSelected ? 'Deleting...' : `Delete Selected (${selectedEvents.size})`}
              </button>
            )}
          </>
        )}
      </div>
      <HelpSpot spotId="events-grid" page="dashboard" order={4} title="Event Cards" description="Your events appear as cards. Click any card to manage its request queue, sync settings, and kiosk controls.">
        <div className="event-grid">
          {events.map((event) => selectionMode ? (
            <div
              key={event.id}
              className="event-card"
              style={{
                cursor: 'pointer', display: 'flex', alignItems: 'flex-start', gap: '0.75rem',
                outline: selectedEvents.has(event.code) ? '2px solid var(--color-primary)' : 'none',
              }}
              onClick={() => toggleEvent(event.code)}
            >
              <input
                type="checkbox"
                checked={selectedEvents.has(event.code)}
                onChange={() => toggleEvent(event.code)}
                onClick={(clickEvent) => clickEvent.stopPropagation()}
                style={{ accentColor: 'var(--color-accent-checkbox)', width: '1rem', height: '1rem', marginTop: '0.25rem', flexShrink: 0 }}
                aria-label={`Select event ${event.code}`}
              />
              <div>
                <h3>{event.name}</h3>
                <div className="code">{event.code}</div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  Expires: {new Date(event.expires_at).toLocaleString()}
                </p>
                {!event.is_active && <span className="badge badge-rejected" style={{ marginTop: '0.5rem' }}>Inactive</span>}
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
                {!event.is_active && <span className="badge badge-rejected" style={{ marginTop: '0.5rem' }}>Inactive</span>}
              </div>
            </Link>
          ))}
        </div>
      </HelpSpot>
    </>
  );
}
