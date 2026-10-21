import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SongRequest } from '@/lib/api/types';
import type { RequestQueueToolbarProps } from '../requestQueueTypes';
import { RequestQueueToolbar } from '../RequestQueueToolbar';

function makeRequest(id: number): SongRequest {
  return { id } as SongRequest;
}

function renderToolbar(overrides: Partial<RequestQueueToolbarProps> = {}, requests = [makeRequest(1)]) {
  const toolbar: RequestQueueToolbarProps = {
    acceptingAll: false,
    onAcceptAll: vi.fn(),
    onRejectAll: vi.fn().mockResolvedValue(undefined),
    onBulkDelete: vi.fn().mockResolvedValue(undefined),
    onEnrichAll: vi.fn().mockResolvedValue({ queued: 1, remaining: 0 }),
    rejectingAll: false,
    sortField: 'date_requested',
    sortDirection: 'desc',
    onSortFieldChange: vi.fn(),
    onSortDirectionToggle: vi.fn(),
    total: requests.length,
    filter: 'all',
    onFilterChange: vi.fn(),
    statusCounts: { all: requests.length, new: requests.length, accepted: 0, playing: 0, played: 0, rejected: 0 },
    ...overrides,
  };

  return render(
    <RequestQueueToolbar
      toolbar={toolbar}
      requests={requests}
      advancedMode
      onAdvancedModeChange={vi.fn()}
      isExpiredOrArchived={false}
      onRefreshMetadata={vi.fn().mockResolvedValue(undefined)}
    />,
  );
}

describe('RequestQueueToolbar enrichment recovery', () => {
  beforeEach(() => {
    vi.spyOn(window, 'alert').mockImplementation(() => undefined);
  });

  afterEach(() => vi.restoreAllMocks());

  it('shows a safe failure and allows retry after enrichment rejects', async () => {
    // Regression for baseline 57cfcdc6867f: failed enrichment must not escape as an unhandled click rejection.
    let rejectEnrichment!: (error: Error) => void;
    const onEnrichAll = vi.fn()
      .mockImplementationOnce(() => new Promise<{ queued: number; remaining: number }>((_resolve, reject) => {
        rejectEnrichment = reject;
      }))
      .mockResolvedValueOnce({ queued: 2, remaining: 0 });
    renderToolbar({ onEnrichAll });

    const enrichButton = screen.getByRole('button', { name: 'Enrich All' });
    fireEvent.click(enrichButton);
    expect(screen.getByRole('button', { name: 'Queuing…' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Queuing…' }));
    expect(onEnrichAll).toHaveBeenCalledTimes(1);

    await act(async () => {
      rejectEnrichment(new Error('provider token and internal endpoint details'));
      await Promise.resolve();
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not queue metadata enrichment/i);
    expect(screen.getByRole('alert')).not.toHaveTextContent(/provider token|internal endpoint/i);
    expect(screen.getByRole('button', { name: 'Enrich All' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Enrich All' }));
    await waitFor(() => expect(window.alert).toHaveBeenCalledWith(expect.stringContaining('Queued enrichment for 2 tracks')));
    expect(onEnrichAll).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each([
    [{ queued: 0, remaining: 3 }, 'All tracks already have BPM, key, and genre.'],
    [{ queued: 2, remaining: 4 }, 'Queued 2 tracks. 4 more remaining'],
    [{ queued: 1, remaining: 0 }, 'Queued enrichment for 1 track.'],
  ] as const)('reports the enrichment result %o', async (result, expectedAlert) => {
    const onEnrichAll = vi.fn().mockResolvedValue(result);
    renderToolbar({ onEnrichAll });

    fireEvent.click(screen.getByRole('button', { name: 'Enrich All' }));

    await waitFor(() => expect(window.alert).toHaveBeenCalledWith(expect.stringContaining(expectedAlert)));
  });
});

describe('RequestQueueToolbar bulk controls', () => {
  beforeEach(() => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
  });

  afterEach(() => vi.restoreAllMocks());

  it('cancels filtered deletion, then confirms it once while the request is pending', async () => {
    let finishDelete!: () => void;
    const onBulkDelete = vi.fn(() => new Promise<void>((resolve) => { finishDelete = resolve; }));
    renderToolbar({
      filter: 'new',
      statusCounts: { all: 3, new: 2, accepted: 1, playing: 0, played: 0, rejected: 0 },
      onBulkDelete,
    });

    const deleteButton = screen.getByRole('button', { name: 'Delete All' });
    fireEvent.click(deleteButton);
    expect(window.confirm).toHaveBeenCalledWith('Delete all 2 new requests? This cannot be undone.');
    expect(onBulkDelete).not.toHaveBeenCalled();

    vi.mocked(window.confirm).mockReturnValue(true);
    fireEvent.click(deleteButton);
    expect(onBulkDelete).toHaveBeenCalledTimes(1);
    expect(onBulkDelete).toHaveBeenCalledWith('new');
    expect(screen.getByRole('button', { name: 'Deleting...' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Deleting...' }));
    expect(onBulkDelete).toHaveBeenCalledTimes(1);

    await act(async () => finishDelete());
    expect(screen.getByRole('button', { name: 'Delete All' })).toBeEnabled();
  });

  it('refreshes the loaded request IDs sequentially and blocks duplicate refresh runs', async () => {
    let finishFirst!: () => void;
    let finishSecond!: () => void;
    const onRefreshMetadata = vi.fn()
      .mockImplementationOnce(() => new Promise<void>((resolve) => { finishFirst = resolve; }))
      .mockImplementationOnce(() => new Promise<void>((resolve) => { finishSecond = resolve; }));
    render(
      <RequestQueueToolbar
        toolbar={{
          acceptingAll: false,
          onAcceptAll: vi.fn(),
          sortField: 'date_requested',
          sortDirection: 'desc',
          onSortFieldChange: vi.fn(),
          onSortDirectionToggle: vi.fn(),
          total: 2,
          filter: 'all',
          onFilterChange: vi.fn(),
          statusCounts: { all: 2, new: 2, accepted: 0, playing: 0, played: 0, rejected: 0 },
        }}
        requests={[makeRequest(11), makeRequest(24)]}
        advancedMode
        onAdvancedModeChange={vi.fn()}
        isExpiredOrArchived={false}
        onRefreshMetadata={onRefreshMetadata}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Refresh All' }));
    expect(onRefreshMetadata).toHaveBeenNthCalledWith(1, 11);
    expect(onRefreshMetadata).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Refreshing...' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Refreshing...' }));
    expect(onRefreshMetadata).toHaveBeenCalledTimes(1);

    await act(async () => finishFirst());
    await waitFor(() => expect(onRefreshMetadata).toHaveBeenNthCalledWith(2, 24));
    expect(onRefreshMetadata).toHaveBeenCalledTimes(2);
    await act(async () => finishSecond());
    expect(screen.getByRole('button', { name: 'Refresh All' })).toBeEnabled();
  });
});
