import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { SongManagementTab } from '../SongManagementTab';

vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({
    helpMode: false, onboardingActive: false, currentStep: 0, activeSpotId: null,
    toggleHelpMode: vi.fn(), registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []), startOnboarding: vi.fn(),
    nextStep: vi.fn(), prevStep: vi.fn(), skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => false),
  }),
}));

vi.mock('../RequestQueueSection', () => ({
  RequestQueueSection: () => <div data-testid="request-queue">RequestQueue</div>,
}));

vi.mock('../../providers/SyncReportPanel', () => ({
  SyncReportPanel: () => <div data-testid="sync-report">SyncReport</div>,
}));

vi.mock('../PlayHistorySection', () => ({
  PlayHistorySection: () => <div data-testid="play-history">PlayHistory</div>,
}));

vi.mock('../../recommendations/RecommendationsCard', () => ({
  RecommendationsCard: () => <div data-testid="recommendations">Recommendations</div>,
}));

vi.mock('../DjSongSearchModal', () => ({
  DjSongSearchModal: ({ onClose, onSongAdded }: { onClose: () => void; onSongAdded: () => void }) => (
    <div data-testid="dj-search">
      <button onClick={onSongAdded}>Add test song</button>
      <button onClick={onClose}>Close song search</button>
    </div>
  ),
}));

const baseProps = {
  isExpiredOrArchived: false,
  requestQueue: {
    requests: [
      { id: 1, song_title: 'Test', artist_name: 'Artist', status: 'accepted', vote_count: 0, created_at: '', event_id: 1 },
    ] as never[],
    rowActions: {
      connectedServices: [],
      updating: null,
      syncingRequest: null,
      onUpdateStatus: vi.fn(),
      onSyncToTidal: vi.fn(),
      onOpenTidalPicker: vi.fn(),
      onScrollToSyncReport: vi.fn(),
    },
    toolbar: {
      acceptingAll: false,
      onAcceptAll: vi.fn(),
      sortField: 'date_requested' as const,
      sortDirection: 'desc' as const,
      onSortFieldChange: vi.fn(),
      onSortDirectionToggle: vi.fn(),
      total: 1,
      onLoadMore: vi.fn(),
      filter: 'all' as const,
      onFilterChange: vi.fn(),
      statusCounts: { all: 1, new: 0, accepted: 1, playing: 0, played: 0, rejected: 0 },
    },
  },
  syncReport: {
    requests: [], connectedServices: [], expanded: false,
    onToggleExpanded: vi.fn(), focusedRequestId: null, onClearFocus: vi.fn(),
    onRetrySync: vi.fn(), onOpenTidalPicker: vi.fn(), onOpenBeatportPicker: vi.fn(),
  },
  playHistory: { items: [], total: 0, exporting: false, onExport: vi.fn() },
  recommendations: { code: 'ABC123', tidalLinked: false, beatportLinked: false, onAcceptTrack: vi.fn() },
  onRefreshRequests: vi.fn(),
};

describe('SongManagementTab', () => {
  it('renders RequestQueueSection', () => {
    render(<SongManagementTab {...baseProps} />);
    expect(screen.getByTestId('request-queue')).toBeInTheDocument();
  });

  it('renders SyncReportPanel', () => {
    render(<SongManagementTab {...baseProps} />);
    expect(screen.getByTestId('sync-report')).toBeInTheDocument();
  });

  it('renders PlayHistorySection', () => {
    render(<SongManagementTab {...baseProps} />);
    expect(screen.getByTestId('play-history')).toBeInTheDocument();
  });

  it('renders RecommendationsCard when not expired', () => {
    render(<SongManagementTab {...baseProps} />);
    expect(screen.getByTestId('recommendations')).toBeInTheDocument();
  });

  it('hides RecommendationsCard when expired', () => {
    render(<SongManagementTab {...baseProps} isExpiredOrArchived={true} />);
    expect(screen.queryByTestId('recommendations')).toBeNull();
  });

  it('opens song search, refreshes after adding a song, and closes the modal', () => {
    const onRefreshRequests = vi.fn();
    render(<SongManagementTab {...baseProps} onRefreshRequests={onRefreshRequests} />);

    fireEvent.click(screen.getByRole('button', { name: 'Search For Song' }));
    expect(screen.getByTestId('dj-search')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Add test song' }));
    expect(onRefreshRequests).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Close song search' }));
    expect(screen.queryByTestId('dj-search')).not.toBeInTheDocument();
  });
});
