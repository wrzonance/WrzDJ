import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import type { SongRequest } from '@/lib/api-types';

// Keep the unit isolated from the heavy api client + UI children.
// A small cap keeps the "hits PUBLIC_PAGE_MAX" test from rendering 500 rows.
vi.mock('@/lib/api', () => ({ PUBLIC_PAGE_MAX: 3 }));
vi.mock('@/components/Tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../SyncStatusBadges', () => ({ SyncStatusBadges: () => null }));
vi.mock('@/components/MusicBadges', () => ({
  KeyBadge: () => null,
  BpmBadge: () => null,
  GenreBadge: () => null,
}));
vi.mock('@/components/PreviewPlayer', () => ({ PreviewPlayer: () => null }));

import { RequestQueueSection } from '../RequestQueueSection';

function makeRequest(overrides: Partial<SongRequest> = {}): SongRequest {
  return {
    id: 1,
    event_id: 1,
    song_title: 'Test Song',
    artist: 'Test Artist',
    source: 'spotify',
    source_url: null,
    artwork_url: null,
    note: null,
    nickname: null,
    status: 'new',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    accepted_at: null,
    is_duplicate: false,
    raw_search_query: null,
    sync_results_json: null,
    vote_count: 0,
    priority_score: null,
    genre: null,
    bpm: null,
    musical_key: null,
    ...overrides,
  };
}

function baseProps(overrides: Record<string, unknown> = {}) {
  return {
    requests: [makeRequest()],
    isExpiredOrArchived: false,
    connectedServices: [],
    updating: null,
    acceptingAll: false,
    syncingRequest: null,
    onUpdateStatus: vi.fn(),
    onAcceptAll: vi.fn(),
    onSyncToTidal: vi.fn(),
    onOpenTidalPicker: vi.fn(),
    sortField: 'date_requested' as const,
    sortDirection: 'desc' as const,
    onSortFieldChange: vi.fn(),
    onSortDirectionToggle: vi.fn(),
    total: 1,
    onLoadMore: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe('RequestQueueSection sort controls', () => {
  it('renders the sort select reflecting the current field', () => {
    render(<RequestQueueSection {...baseProps({ sortField: 'best_match' })} />);
    const select = screen.getByLabelText('Sort requests by') as HTMLSelectElement;
    expect(select.value).toBe('best_match');
  });

  it('calls onSortFieldChange when a new field is picked', () => {
    const onSortFieldChange = vi.fn();
    render(<RequestQueueSection {...baseProps({ onSortFieldChange })} />);
    fireEvent.change(screen.getByLabelText('Sort requests by'), {
      target: { value: 'upvotes' },
    });
    expect(onSortFieldChange).toHaveBeenCalledWith('upvotes');
  });

  it('calls onSortDirectionToggle when the direction button is clicked', () => {
    const onSortDirectionToggle = vi.fn();
    render(<RequestQueueSection {...baseProps({ onSortDirectionToggle, sortDirection: 'asc' })} />);
    fireEvent.click(screen.getByLabelText(/Sort direction/));
    expect(onSortDirectionToggle).toHaveBeenCalledTimes(1);
  });

  it('shows ↑ for asc and ↓ for desc', () => {
    const { rerender } = render(<RequestQueueSection {...baseProps({ sortDirection: 'asc' })} />);
    expect(screen.getByLabelText('Sort direction: ascending')).toHaveTextContent('↑');
    rerender(<RequestQueueSection {...baseProps({ sortDirection: 'desc' })} />);
    expect(screen.getByLabelText('Sort direction: descending')).toHaveTextContent('↓');
  });
});

describe('RequestQueueSection Load More', () => {
  it('shows "Showing X of N" and a Load More button when more rows exist', () => {
    render(<RequestQueueSection {...baseProps({ requests: [makeRequest()], total: 5 })} />);
    expect(screen.getByText('Showing 1 of 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load More' })).toBeInTheDocument();
  });

  it('hides the Load More button once everything is loaded', () => {
    const reqs = [makeRequest({ id: 1 }), makeRequest({ id: 2 })];
    render(<RequestQueueSection {...baseProps({ requests: reqs, total: 2 })} />);
    expect(screen.getByText('Showing 2 of 2')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load More' })).toBeNull();
  });

  it('hides Load More at the PUBLIC_PAGE_MAX cap even if total is larger', () => {
    // PUBLIC_PAGE_MAX is mocked to 3 above, so 3 loaded rows hits the cap.
    const reqs = Array.from({ length: 3 }, (_, i) => makeRequest({ id: i + 1 }));
    render(<RequestQueueSection {...baseProps({ requests: reqs, total: 900 })} />);
    expect(screen.getByText('Showing 3 of 900')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load More' })).toBeNull();
  });

  it('invokes onLoadMore with the active status filter', async () => {
    const onLoadMore = vi.fn().mockResolvedValue(undefined);
    render(<RequestQueueSection {...baseProps({ onLoadMore, total: 5 })} />);
    // Default filter is "all" → status omitted (undefined).
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Load More' }));
    });
    expect(onLoadMore).toHaveBeenCalledWith(undefined);
  });
});
