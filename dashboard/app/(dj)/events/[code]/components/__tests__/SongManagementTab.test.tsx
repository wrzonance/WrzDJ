import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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

vi.mock('../SyncReportPanel', () => ({
  SyncReportPanel: () => <div data-testid="sync-report">SyncReport</div>,
}));

vi.mock('../PlayHistorySection', () => ({
  PlayHistorySection: () => <div data-testid="play-history">PlayHistory</div>,
}));

vi.mock('../RecommendationsCard', () => ({
  RecommendationsCard: () => <div data-testid="recommendations">Recommendations</div>,
}));

vi.mock('../DjSongSearchModal', () => ({
  DjSongSearchModal: () => <div data-testid="dj-search">DjSearch</div>,
}));

const baseProps = {
  code: 'ABC123',
  requests: [
    { id: 1, song_title: 'Test', artist_name: 'Artist', status: 'accepted', vote_count: 0, created_at: '', event_id: 1 },
  ] as never[],
  isExpiredOrArchived: false,
  connectedServices: [],
  updating: null,
  acceptingAll: false,
  syncingRequest: null,
  onUpdateStatus: vi.fn(),
  onAcceptAll: vi.fn(),
  onSyncToTidal: vi.fn(),
  onOpenTidalPicker: vi.fn(),
  onOpenBeatportPicker: vi.fn(),
  onScrollToSyncReport: vi.fn(),
  syncReportExpanded: false,
  onToggleSyncReport: vi.fn(),
  focusedSyncRequestId: null,
  onClearSyncFocus: vi.fn(),
  playHistory: [],
  playHistoryTotal: 0,
  exportingHistory: false,
  onExportPlayHistory: vi.fn(),
  tidalLinked: false,
  beatportLinked: false,
  onAcceptTrack: vi.fn(),
  onRefreshRequests: vi.fn(),
  sortField: 'date_requested' as const,
  sortDirection: 'desc' as const,
  onSortFieldChange: vi.fn(),
  onSortDirectionToggle: vi.fn(),
  total: 1,
  onLoadMore: vi.fn(),
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
});
