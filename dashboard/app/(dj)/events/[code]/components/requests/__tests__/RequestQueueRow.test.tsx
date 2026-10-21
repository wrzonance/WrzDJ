import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SongRequest } from '@/lib/api/types';
import { computeBpmContext } from '@/lib/bpm-stats';
import { RequestQueueRow } from '../RequestQueueRow';
import type { RequestRowActions, RequestRowPresentation } from '../requestQueueTypes';

vi.mock('@/components/Tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../../providers/SyncStatusBadges', () => ({ SyncStatusBadges: () => null }));
vi.mock('@/components/MusicBadges', () => ({
  KeyBadge: () => null,
  BpmBadge: () => null,
  GenreBadge: () => null,
}));
vi.mock('@/components/PreviewPlayer', () => ({ PreviewPlayer: () => null }));

const baseRequest: SongRequest = {
  id: 73,
  event_id: 12,
  song_title: 'Example Track',
  artist: 'Example Artist',
  source: 'spotify',
  source_url: 'https://open.spotify.com/track/example',
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
};

function defaultActions(): RequestRowActions {
  return {
    connectedServices: [],
    bridgeConnected: false,
    updating: null,
    syncingRequest: null,
    onUpdateStatus: vi.fn(),
    onSyncToTidal: vi.fn(),
    onOpenTidalPicker: vi.fn(),
    onDeleteRequest: vi.fn().mockResolvedValue(undefined),
    onRefreshMetadata: vi.fn().mockResolvedValue(undefined),
    deletingRequest: null,
    refreshingRequest: null,
  };
}

function defaultPresentation(): RequestRowPresentation {
  return {
    isExpiredOrArchived: false,
    sortField: 'date_requested',
    advancedMode: false,
    bpmContext: computeBpmContext([]),
  };
}

function renderRow(options: {
  request?: Partial<SongRequest>;
  actions?: Partial<RequestRowActions>;
  presentation?: Partial<RequestRowPresentation>;
} = {}) {
  const request = { ...baseRequest, ...options.request };
  const actions = { ...defaultActions(), ...options.actions };
  const presentation = { ...defaultPresentation(), ...options.presentation };
  const result = render(<RequestQueueRow request={request} actions={actions} presentation={presentation} />);
  return { request, actions, ...result };
}

describe('RequestQueueRow', () => {
  beforeEach(() => vi.restoreAllMocks());

  it.each([
    ['Accept', 'new', 'accepted'],
    ['Reject', 'new', 'rejected'],
    ['Mark Playing', 'accepted', 'playing'],
    ['Played', 'playing', 'played'],
  ] as const)(
    'clicking %s sends the request ID and changes %s to %s',
    (button, status, nextStatus) => {
      const { request, actions } = renderRow({ request: { status } });

      fireEvent.click(screen.getByRole('button', { name: button }));

      expect(actions.onUpdateStatus).toHaveBeenCalledWith(request.id, nextStatus);
    },
  );

  it('hides manual playing for accepted rows with a connected bridge unless advanced mode is on', () => {
    const actions = defaultActions();
    const { rerender } = render(<RequestQueueRow
      request={{ ...baseRequest, status: 'accepted' }}
      actions={{ ...actions, bridgeConnected: true }}
      presentation={defaultPresentation()}
    />);
    expect(screen.queryByRole('button', { name: 'Mark Playing' })).not.toBeInTheDocument();

    rerender(<RequestQueueRow
      request={{ ...baseRequest, status: 'accepted' }}
      actions={{ ...actions, bridgeConnected: true }}
      presentation={{ ...defaultPresentation(), advancedMode: true }}
    />);
    expect(screen.getByRole('button', { name: 'Mark Playing' })).toBeInTheDocument();
  });

  it('hides status and advanced actions for expired or archived events', () => {
    renderRow({ presentation: { advancedMode: true, isExpiredOrArchived: true } });

    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Refresh' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('disables status changes while a request update is pending', () => {
    const { actions } = renderRow({ actions: { updating: 11 } });
    const accept = screen.getByRole('button', { name: 'Accept' });
    const reject = screen.getByRole('button', { name: 'Reject' });

    expect(accept).toBeDisabled();
    expect(reject).toBeDisabled();
    fireEvent.click(accept);
    fireEvent.click(reject);
    expect(actions.onUpdateStatus).not.toHaveBeenCalled();
  });

  it('confirms delete and passes the request ID, while cancellation does nothing', () => {
    const { request, actions } = renderRow({ presentation: { advancedMode: true } });
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    const deleteButton = screen.getByRole('button', { name: 'Delete' });

    fireEvent.click(deleteButton);
    expect(actions.onDeleteRequest).not.toHaveBeenCalled();
    fireEvent.click(deleteButton);

    expect(window.confirm).toHaveBeenCalledWith('Delete "Example Track" by Example Artist?');
    expect(actions.onDeleteRequest).toHaveBeenCalledWith(request.id);
  });

  it('refreshes metadata for this request and disables duplicate pending actions', () => {
    const { request, actions, rerender } = renderRow({ presentation: { advancedMode: true } });
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(actions.onRefreshMetadata).toHaveBeenCalledWith(request.id);

    const pendingActions = { ...defaultActions(), refreshingRequest: request.id, deletingRequest: request.id };
    rerender(<RequestQueueRow
      request={request}
      actions={pendingActions}
      presentation={{ ...defaultPresentation(), advancedMode: true }}
    />);
    expect(screen.getAllByRole('button', { name: '...' })).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: '...' }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    const pendingDelete = screen.getAllByRole('button', { name: '...' })[1];
    expect(pendingDelete).toBeDisabled();
    fireEvent.click(screen.getAllByRole('button', { name: '...' })[0]);
    fireEvent.click(pendingDelete);
    expect(pendingActions.onRefreshMetadata).not.toHaveBeenCalled();
    expect(pendingActions.onDeleteRequest).not.toHaveBeenCalled();
  });

  it('renders only a safe external source link', () => {
    const { rerender } = render(<RequestQueueRow
      request={baseRequest}
      actions={defaultActions()}
      presentation={defaultPresentation()}
    />);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', 'https://open.spotify.com/track/example');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');

    rerender(<RequestQueueRow
      request={{ ...baseRequest, source_url: 'javascript:alert(1)' }}
      actions={defaultActions()}
      presentation={defaultPresentation()}
    />);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
