import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api.js';
import type { EventInfo } from '../../shared/types.js';

const POLL_INTERVAL_MS = 30_000;

interface EventSelectorProps {
  selectedCode: string | null;
  onSelect: (event: EventInfo) => void;
  onEventRemoved?: (code: string) => void;
}

export function EventSelector({ selectedCode, onSelect, onEventRemoved }: EventSelectorProps) {
  const [events, setEvents] = useState<readonly EventInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const selectedCodeRef = useRef(selectedCode);
  selectedCodeRef.current = selectedCode;

  const loadEvents = useCallback(async (isBackground = false) => {
    if (!isBackground) {
      setLoading(true);
    }
    setError(null);
    try {
      const result = await api.fetchEvents();
      setEvents(result);

      // If the selected event is no longer in the list, notify parent
      const currentCode = selectedCodeRef.current;
      if (currentCode && !result.some((e) => e.code === currentCode)) {
        onEventRemoved?.(currentCode);
      }
    } catch (err) {
      // Only show errors on foreground loads — don't disrupt with transient poll failures
      if (!isBackground) {
        setError(err instanceof Error ? err.message : 'Failed to load events');
      }
    } finally {
      if (!isBackground) {
        setLoading(false);
      }
    }
  }, [onEventRemoved]);

  // Initial load
  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  // Periodic background refresh
  useEffect(() => {
    const timer = setInterval(() => {
      loadEvents(true);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [loadEvents]);

  if (loading) {
    return (
      <div className="card">
        <div className="card-title">Select Event</div>
        <p style={{ color: '#9ca3af', fontSize: '0.85rem' }}>Loading events...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <div className="card-title">Select Event</div>
        <div className="error-message">{error}</div>
        <button className="btn btn-ghost btn-sm" onClick={() => loadEvents()}>
          Retry
        </button>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="card">
        <div className="card-title">Select Event</div>
        <p style={{ color: '#9ca3af', fontSize: '0.85rem' }}>
          No active events. Create an event on the WrzDJ dashboard first.
        </p>
        <button className="btn btn-ghost btn-sm" onClick={() => loadEvents()} style={{ marginTop: '0.5rem' }}>
          Refresh
        </button>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-title">Select Event</div>
      <div className="event-list">
        {events.map((event) => (
          <div
            key={event.id}
            className={`event-item ${selectedCode === event.code ? 'selected' : ''}`}
            onClick={() => onSelect(event)}
          >
            <span className="event-item-name">{event.name}</span>
            <span className="event-item-code">{event.joinCode}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
