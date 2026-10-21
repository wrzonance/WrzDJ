'use client';

import { useEffect, useRef, useState } from 'react';
import { api, type AdminGuest, type AdminGuestFilter } from '@/lib/api';
import { useAdminPage } from '@/lib/use-admin-page';
import { HelpSpot } from '@/components/help/HelpSpot';
import { HelpButton } from '@/components/help/HelpButton';
import { OnboardingOverlay } from '@/components/help/OnboardingOverlay';
import { GuestEditModal } from './components/GuestEditModal';
import { GuestRow } from './components/GuestRow';
import { GUEST_TABLE_COLUMNS, guestDisplayName } from './components/guest-format';

const PAGE_ID = 'admin-guests';
const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;

const FILTERS: { label: string; value: AdminGuestFilter }[] = [
  { label: 'All', value: 'all' },
  { label: 'Verified', value: 'verified' },
  { label: 'Unverified', value: 'unverified' },
  { label: 'Shared fingerprint', value: 'shared' },
];

const DELETE_CONFIRM =
  'Their event memberships are removed; their requests and votes stay but become anonymous.';

export default function AdminGuestsPage() {
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<AdminGuestFilter>('all');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState<string | undefined>();
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [editGuest, setEditGuest] = useState<AdminGuest | null>(null);
  const [error, setError] = useState('');

  const { data: paginated, error: loadError, loading, reload } = useAdminPage({
    pageId: PAGE_ID,
    loader: () => api.getAdminGuests(page, PAGE_SIZE, filter, query),
    onError: () => 'Failed to load guests',
  });
  const guests = paginated?.items ?? [];
  const total = paginated?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  // Debounced search: only a *changed* query resets the page, so the mount-time
  // timer cannot bounce an admin who already clicked Next back to page 1.
  const appliedQueryRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    const timer = setTimeout(() => {
      const next = search.trim() || undefined;
      if (next === appliedQueryRef.current) return;
      appliedQueryRef.current = next;
      setQuery(next);
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  // Deleting the last guest on a later page would otherwise strand the admin
  // on an empty page with no pagination to go back.
  useEffect(() => {
    if (!loading && total > 0 && page > totalPages) setPage(totalPages);
  }, [loading, total, page, totalPages]);

  // useAdminPage already loads once on mount; this effect covers later changes.
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }
    reload();
  }, [page, filter, query, reload]);

  const selectFilter = (value: AdminGuestFilter) => {
    setFilter(value);
    setPage(1);
    setExpandedId(null);
  };

  const handleDelete = async (guest: AdminGuest) => {
    if (!window.confirm(`Delete guest "${guestDisplayName(guest)}"? ${DELETE_CONFIRM}`)) return;
    setError('');
    try {
      await api.deleteAdminGuest(guest.id);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete guest');
    }
  };

  const handleSaved = () => {
    setEditGuest(null);
    reload();
  };

  return (
    <div className="container">
      <HelpButton page={PAGE_ID} />
      <OnboardingOverlay page={PAGE_ID} />

      <HelpSpot
        spotId="admin-guests-header"
        page={PAGE_ID}
        order={1}
        title="Guest Management"
        description="Everyone who has joined an event: their verification, bot signals, and memberships."
      >
        <div className="header">
          <div className="guest-heading">
            <h1>Guest Management</h1>
            {!loading && (
              <span className="guest-meta">{total === 1 ? '1 guest' : `${total} guests`}</span>
            )}
          </div>
        </div>
      </HelpSpot>

      {(error || loadError) && (
        <div style={{ color: 'var(--color-danger)', marginBottom: '1rem' }}>{error || loadError}</div>
      )}

      <HelpSpot
        spotId="admin-guests-filters"
        page={PAGE_ID}
        order={2}
        title="Filters and search"
        description="Narrow to verified or unverified guests, or to fingerprints shared by several guests (a bot-farm or shared-device signal). Search matches any event nickname."
      >
        <div className="guest-toolbar">
          <div className="tabs" style={{ marginBottom: 0 }}>
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                className={`tab${filter === f.value ? ' active' : ''}`}
                onClick={() => selectFilter(f.value)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <input
            type="search"
            className="input guest-search"
            aria-label="Search by nickname"
            placeholder="Search by nickname"
            value={search}
            maxLength={30}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </HelpSpot>

      {editGuest && (
        <GuestEditModal guest={editGuest} onClose={() => setEditGuest(null)} onSaved={handleSaved} />
      )}

      {loading ? (
        <div className="loading">Loading guests...</div>
      ) : (
        <>
          <HelpSpot
            spotId="admin-guests-table"
            page={PAGE_ID}
            order={3}
            title="Guest table"
            description="Email shows whether the guest proved an address. Human counts Turnstile passes. Fingerprint flags browsers that several guests share."
          >
            <table className="admin-table guest-table">
              <thead>
                <tr>
                  <th>Guest</th>
                  <th>Email</th>
                  <th>Human</th>
                  <th>Fingerprint</th>
                  <th>Joined</th>
                  <th>Last seen</th>
                  <th>Events</th>
                  <th>
                    <HelpSpot
                      spotId="admin-guests-actions"
                      page={PAGE_ID}
                      order={4}
                      title="Guest actions"
                      description="Edit event nicknames or revoke a verified email. Delete removes the identity; their requests stay, anonymised."
                    >
                      <span>Actions</span>
                    </HelpSpot>
                  </th>
                </tr>
              </thead>
              <tbody>
                {guests.length === 0 ? (
                  <tr>
                    <td colSpan={GUEST_TABLE_COLUMNS} className="guest-empty">
                      No guests match this filter.
                    </td>
                  </tr>
                ) : (
                  guests.map((guest) => (
                    <GuestRow
                      key={guest.id}
                      guest={guest}
                      expanded={expandedId === guest.id}
                      onToggle={() => setExpandedId(expandedId === guest.id ? null : guest.id)}
                      onEdit={() => {
                        setEditGuest(guest);
                        setError('');
                      }}
                      onDelete={() => handleDelete(guest)}
                    />
                  ))
                )}
              </tbody>
            </table>
          </HelpSpot>

          {totalPages > 1 && (
            <div className="pagination">
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </button>
              <span style={{ color: 'var(--text-secondary)' }}>
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
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
