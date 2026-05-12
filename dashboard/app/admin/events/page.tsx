'use client';

import { useEffect, useState } from 'react';
import { api, AdminEvent } from '@/lib/api';
import { useAdminPage } from '@/lib/useAdminPage';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';

const PAGE_ID = 'admin-events';

export default function AdminEventsPage() {
  const [page, setPage] = useState(1);
  const [editEvent, setEditEvent] = useState<AdminEvent | null>(null);
  const [editName, setEditName] = useState('');
  const [error, setError] = useState('');
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(new Set());
  const [deletingSelected, setDeletingSelected] = useState(false);
  const limit = 20;

  const { data: paginated, error: loadError, loading, reload } = useAdminPage({
    pageId: PAGE_ID,
    loader: () => api.getAdminEvents(page, limit),
    onError: () => 'Failed to load events',
  });
  const events = paginated?.items ?? [];
  const total = paginated?.total ?? 0;

  useEffect(() => {
    setSelectedEvents(new Set());
    reload();
  }, [page, reload]);

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editEvent) return;
    setError('');
    try {
      await api.updateAdminEvent(editEvent.code, { name: editName });
      setEditEvent(null);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update event');
    }
  };

  const handleDelete = async (event: AdminEvent) => {
    if (!confirm(`Delete event "${event.name}" (${event.code})? This cannot be undone.`)) return;
    try {
      await api.deleteAdminEvent(event.code);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete event');
    }
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
      await api.bulkDeleteAdminEvents([...selectedEvents]);
      setSelectedEvents(new Set());
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete events');
    } finally {
      setDeletingSelected(false);
    }
  };

  const totalPages = Math.ceil(total / limit);

  return (
    <div className="container">
      <HelpButton page={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />

      <HelpSpot spotId="admin-events-header" page={PAGE_ID} order={1} title="Event Management" description="View and manage all events across the platform.">
        <div className="header">
          <h1>Event Management</h1>
        </div>
      </HelpSpot>

      {(error || loadError) && (
        <div style={{ color: 'var(--color-danger)', marginBottom: '1rem' }}>{error || loadError}</div>
      )}

      {/* Edit Modal */}
      {editEvent && (
        <div className="modal-overlay" onClick={() => setEditEvent(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2 style={{ marginBottom: '1rem' }}>Edit: {editEvent.code}</h2>
            <form onSubmit={handleEdit}>
              <div className="form-group">
                <label htmlFor="edit-event-name">Event Name</label>
                <input
                  id="edit-event-name"
                  className="input"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  required
                />
              </div>
              <div style={{ display: 'flex', gap: '1rem' }}>
                <button type="submit" className="btn btn-primary">Save</button>
                <button
                  type="button"
                  className="btn"
                  style={{ background: 'var(--surface-raised)' }}
                  onClick={() => setEditEvent(null)}
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">Loading events...</div>
      ) : (
        <>
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
            {selectionMode && selectedEvents.size > 0 && (
              <button
                className="btn btn-sm btn-danger"
                onClick={handleBulkDelete}
                disabled={deletingSelected}
              >
                {deletingSelected ? 'Deleting...' : `Delete Selected (${selectedEvents.size})`}
              </button>
            )}
          </div>

          <HelpSpot spotId="admin-events-table" page={PAGE_ID} order={2} title="Events Table" description="Every event with code, owner, request count, and Active/Expired/Inactive status.">
            <table className="admin-table">
              <thead>
                <tr>
                  {selectionMode && (
                    <th>
                      <input
                        type="checkbox"
                        checked={selectedEvents.size === events.length && events.length > 0}
                        onChange={toggleSelectAll}
                        style={{ accentColor: 'var(--color-accent-checkbox)' }}
                        aria-label="Select All"
                      />
                    </th>
                  )}
                  <th>Code</th>
                  <th>Name</th>
                  <th>Owner</th>
                  <th>Requests</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>
                    <HelpSpot spotId="admin-events-actions" page={PAGE_ID} order={3} title="Event Actions" description="Rename or delete any event. Deleting removes all requests permanently.">
                      <span>Actions</span>
                    </HelpSpot>
                  </th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    {selectionMode && (
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedEvents.has(event.code)}
                          onChange={() => toggleSelection(event.code)}
                          style={{ accentColor: 'var(--color-accent-checkbox)' }}
                          aria-label={`Select event ${event.code}`}
                        />
                      </td>
                    )}
                    <td style={{ fontFamily: 'monospace', color: 'var(--color-primary)' }}>{event.code}</td>
                    <td>{event.name}</td>
                    <td>{event.owner_username}</td>
                    <td>{event.request_count}</td>
                    <td>
                      {event.is_active ? (
                        new Date(event.expires_at) > new Date() ? (
                          <span className="badge badge-playing">Active</span>
                        ) : (
                          <span className="badge badge-played">Expired</span>
                        )
                      ) : (
                        <span className="badge badge-rejected">Inactive</span>
                      )}
                    </td>
                    <td>{new Date(event.created_at).toLocaleDateString()}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button
                          className="btn btn-sm btn-primary"
                          onClick={() => {
                            setEditEvent(event);
                            setEditName(event.name);
                            setError('');
                          }}
                        >
                          Edit
                        </button>
                        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(event)}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </HelpSpot>

          {totalPages > 1 && (
            <div className="pagination">
              <button
                className="btn btn-sm"
                style={{ background: 'var(--surface-raised)' }}
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <span style={{ color: 'var(--text-secondary)' }}>
                Page {page} of {totalPages}
              </span>
              <button
                className="btn btn-sm"
                style={{ background: 'var(--surface-raised)' }}
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
